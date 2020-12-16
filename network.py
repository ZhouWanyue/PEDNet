#!/usr/bin/env python
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2019 Baidu.com, Inc. All Rights Reserved
#
################################################################################
import os
import sys
import json
import shutil
import logging
import argparse
import torch
from datetime import datetime
from source.inputters.corpus import PersonaCorpus
from source.models.alternative_persona_seq2seq import TwoStagePersonaSeq2Seq
# from source.models.seq2seq import Seq2Seq
from source.utils.engine import Trainer
from source.utils.generator import TopKGenerator
from source.utils.engine import evaluate, evaluate_generation
from source.utils.misc import str2bool
from source.utils.optim import ScheduledOptim


def model_config():
    """
    model_config
    """
    parser = argparse.ArgumentParser()  # 创建 ArgumentParser() 对象

    # Data
    data_arg = parser.add_argument_group("Data")
    data_arg.add_argument("--data_dir", type=str, default="./data/")  # 调用 add_argument() 方法添加参数
    data_arg.add_argument("--data_prefix", type=str, default="demo")
    data_arg.add_argument("--save_dir", type=str, default="./models(1)/")
    data_arg.add_argument("--with_label", type=str2bool, default=True)
    data_arg.add_argument("--embed_file", type=str, default="./data/glove.840B.300d.txt")

    # Network
    net_arg = parser.add_argument_group("Network")
    net_arg.add_argument("--embed_size", type=int, default=300)
    net_arg.add_argument("--hidden_size", type=int, default=800)
    net_arg.add_argument("--bidirectional", type=str2bool, default=True)
    net_arg.add_argument("--max_vocab_size", type=int, default=20000)
    net_arg.add_argument("--min_len", type=int, default=1)
    net_arg.add_argument("--max_len", type=int, default=50)
    net_arg.add_argument("--num_layers", type=int, default=2)
    net_arg.add_argument("--attn", type=str, default='dot',
                         choices=['none', 'mlp', 'dot', 'general'])
    net_arg.add_argument("--share_vocab", type=str2bool, default=True)
    net_arg.add_argument("--with_bridge", type=str2bool, default=False)
    net_arg.add_argument("--tie_embedding", type=str2bool, default=True)

    # Training / Testing
    train_arg = parser.add_argument_group("Training")
    train_arg.add_argument("--optimizer", type=str, default="Adam")
    train_arg.add_argument("--lr", type=float, default=0.0005)
    train_arg.add_argument("--grad_clip", type=float, default=5.0)
    train_arg.add_argument("--dropout", type=float, default=0.2)
    train_arg.add_argument("--num_epochs", type=int, default=50)
    train_arg.add_argument("--pretrain_epoch", type=int, default=0)
    train_arg.add_argument("--lr_decay", type=float, default=0.5)
    train_arg.add_argument("--num_warmup", type=int, default=8000)
    train_arg.add_argument("--use_embed", type=str2bool, default=True)
    train_arg.add_argument("--use_dssm", type=str2bool, default=False)
    train_arg.add_argument("--use_pg", type=str2bool, default=False)
    train_arg.add_argument("--weight_control", type=str2bool, default=False)
    train_arg.add_argument("--decode_concat", type=str2bool, default=False)

    # Geneation
    gen_arg = parser.add_argument_group("Generation")
    gen_arg.add_argument("--max_dec_len", type=int, default=30)
    gen_arg.add_argument("--ignore_unk", type=str2bool, default=True)
    gen_arg.add_argument("--length_average", type=str2bool, default=True)
    gen_arg.add_argument("--gen_file", type=str, default="./output_1query_0.5/multitask36.result")
    gen_arg.add_argument("--gold_score_file", type=str, default="./gold.scores")

    # MISC
    misc_arg = parser.add_argument_group("Misc")
    misc_arg.add_argument("--gpu", type=int, default=0)
    misc_arg.add_argument("--log_steps", type=int, default=100)
    misc_arg.add_argument("--valid_steps", type=int, default=500)
    misc_arg.add_argument("--batch_size", type=int, default=128)
    # misc_arg.add_argument("--ckpt", type=str, default="models(20-2)/state_epoch_43.model")
    misc_arg.add_argument("--ckpt", type=str, default="models(1)/state_epoch_36.model")
    # misc_arg.add_argument("--ckpt", type=str, default="models/best.model")
    # misc_arg.add_argument("--ckpt", type=str, default=None)

    misc_arg.add_argument("--check", type=str2bool, default=False)
    misc_arg.add_argument("--test", type=str2bool, default=True)
    misc_arg.add_argument("--interact", type=str2bool, default=False)
    # misc_arg.add_argument("--interact", type=str2bool, default=True)

    config = parser.parse_args()  # 使用 parse_args() 解析添加的参数

    return config


def main():
    """
    main
    """
    config = model_config()
    if config.check:
        config.save_dir = "./tmp/"
    config.use_gpu = torch.cuda.is_available() and config.gpu >= 0
    device = config.gpu
    torch.cuda.set_device(device)
    # Data definition
    corpus = PersonaCorpus(data_dir=config.data_dir, data_prefix=config.data_prefix,
                           min_freq=0, max_vocab_size=config.max_vocab_size,
                           min_len=config.min_len, max_len=config.max_len,
                           embed_file=config.embed_file, with_label=config.with_label,
                           share_vocab=config.share_vocab)
    corpus.load()  # 加载准备文件prepared_data_file和prepared_vocab_file，词表建好，data中的词也变成了索引，且data = {"train": train_data,"valid": valid_data,"test": test_data}
    if config.test and config.ckpt:
        corpus.reload(data_type='test')  # 重新加载，加载的测试用的数据
    train_iter = corpus.create_batches(
        config.batch_size, "train", shuffle=True, device=device)  # 批训练的迭代器
    '''
    以第二阶段为例
    #Dataloader 嵌套形式为[分离batch->{分离src和target->(分离数据和长度->tensor数据值    
    #[
      {'src':( 数据值-->shape(batch_size, max_len), 句子长度值--> shape(batch_size) ),
      'tgt':( 数据值-->shape(batch_size , max_len), 句子长度值-->shape(batch_size) )，
      'cue' :( 数据值-->shape(batch_size , sen_num , max_len), 句子长度值--> shape(batch_size，sen_num) )
      'label':( 数据值-->shape(batch_size , max_len), 句子长度值-->shape(batch_size) )，
      'index': ( 数据值-->shape(batch_size , max_len), 句子长度值-->shape(batch_size) )，
      },
      {},
      {},
      {}，……………………………………
     ]
    '''
    valid_iter = corpus.create_batches(
        config.batch_size, "valid", shuffle=False, device=device)
    test_iter = corpus.create_batches(
        config.batch_size, "test", shuffle=False, device=device)
    # Model definition

    model = TwoStagePersonaSeq2Seq(src_vocab_size=corpus.SRC.vocab_size,
                                   tgt_vocab_size=corpus.TGT.vocab_size,  # 是建词表时算出来的TGT的词表长度
                                   embed_size=config.embed_size, hidden_size=config.hidden_size,
                                   padding_idx=corpus.padding_idx,
                                   num_layers=config.num_layers, bidirectional=config.bidirectional,
                                   attn_mode=config.attn, with_bridge=config.with_bridge,
                                   tie_embedding=config.tie_embedding, dropout=config.dropout,
                                   use_gpu=config.use_gpu,
                                   use_dssm=config.use_dssm,
                                   use_pg=config.use_pg,
                                   pretrain_epoch=config.pretrain_epoch,
                                   weight_control=config.weight_control,
                                   concat=config.decode_concat,
                                   with_label=config.with_label)
    '''model = seq2seq(src_vocab_size=corpus.SRC.vocab_size,
                 tgt_vocab_size=corpus.TGT.vocab_size,
                 embed_size=config.embed_size, hidden_size=config.hidden_size,
                 padding_idx=corpus.padding_idx,
                 num_layers=config.num_layers,
                 bidirectional=config.bidirectional,
                 attn_mode=config.attn,
                 attn_hidden_size=None,
                 with_bridge=config.with_bridge,
                 tie_embedding=config.tie_embedding,
                 dropout=config.dropout,
                 use_gpu=config.use_gpu'''

    model_name = model.__class__.__name__
    # Generator definition
    generator = TopKGenerator(model=model,
                              src_field=corpus.SRC, tgt_field=corpus.TGT, cue_field=corpus.CUE,
                              max_length=config.max_dec_len, ignore_unk=config.ignore_unk,
                              length_average=config.length_average, use_gpu=config.use_gpu)
    # Interactive generation testing
    if config.interact and config.ckpt:
        model.load(config.ckpt)
        return generator
    # Testing
    elif config.test and config.ckpt:
        print(model)
        model.load(config.ckpt)
        print("Testing ...")
        metrics, scores = evaluate(model, test_iter)
        print(metrics.report_cum())
        print("Generating ...")
        evaluate_generation(generator, test_iter, save_file=config.gen_file, verbos=True)
    else:
        # Load word embeddings
        if config.use_embed and config.embed_file is not None:
            model.encoder.embedder.load_embeddings(
                corpus.SRC.embeddings, scale=0.03)
            model.decoder.embedder.load_embeddings(
                corpus.TGT.embeddings, scale=0.03)

        # Optimizer definition
        optimizer = getattr(torch.optim, config.optimizer)(
            model.parameters(), lr=config.lr)

        # scheduloptimizer = ScheduledOptim(optimizer, config.hidden_size, config.num_warmup)
        # Learning rate scheduler
        if config.lr_decay is not None and 0 < config.lr_decay < 1.0:
            lr_scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer=optimizer,
                                                                      factor=config.lr_decay, patience=3, verbose=True,
                                                                      min_lr=1e-5)
        else:
            lr_scheduler = None
        # Save directory
        date_str, time_str = datetime.now().strftime("%Y%m%d-%H%M%S").split("-")
        result_str = "{}-{}".format(model_name, time_str)
        if not os.path.exists(config.save_dir):
            os.makedirs(config.save_dir)
        # Logger definition
        logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.DEBUG, format="%(message)s")
        fh = logging.FileHandler(os.path.join(config.save_dir, "train.log"))
        logger.addHandler(fh)
        # Save config
        params_file = os.path.join(config.save_dir, "params.json")
        with open(params_file, 'w') as fp:
            json.dump(config.__dict__, fp, indent=4, sort_keys=True)
        print("Saved params to '{}'".format(params_file))
        logger.info(model)
        # Train
        logger.info("Training starts ...")
        trainer = Trainer(model=model, optimizer=optimizer, train_iter=train_iter,
                          valid_iter=valid_iter, logger=logger, generator=generator,
                          valid_metric_name="-loss", num_epochs=config.num_epochs,
                          save_dir=config.save_dir, log_steps=config.log_steps,
                          valid_steps=config.valid_steps, grad_clip=config.grad_clip,
                          lr_scheduler=lr_scheduler, save_summary=False)
        if config.ckpt is not None:
            trainer.load(file_prefix=config.ckpt)
        trainer.train()
        logger.info("Training done!")
        # Test
        logger.info("")
        trainer.load(os.path.join(config.save_dir, "best"))
        logger.info("Testing starts ...")
        metrics, scores = evaluate(model, test_iter)
        logger.info(metrics.report_cum())
        logger.info("Generation starts ...")
        test_gen_file = os.path.join(config.save_dir, "test.result")
        evaluate_generation(generator, test_iter, save_file=test_gen_file, verbos=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nExited from the program ealier!")
