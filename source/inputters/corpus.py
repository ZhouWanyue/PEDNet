#!/usr/bin/env python
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2019 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
File: source/inputters/corpus.py
"""

import os
import torch

from tqdm import tqdm
from source.inputters.field import tokenize
from source.inputters.field import TextField
from source.inputters.field import NumberField
from source.inputters.dataset import Dataset


class Corpus(object):
    """
    Corpus
    """
    def __init__(self,
                 data_dir,
                 data_prefix,
                 min_freq=0,
                 max_vocab_size=None):
        self.data_dir = data_dir
        self.data_prefix = data_prefix
        self.min_freq = min_freq
        self.max_vocab_size = max_vocab_size

        prepared_data_file = data_prefix + "_" + str(max_vocab_size) + ".data.pt"
        prepared_vocab_file = data_prefix + "_" + str(max_vocab_size) + ".vocab.pt"

        self.prepared_data_file = os.path.join(data_dir, prepared_data_file)
        self.prepared_vocab_file = os.path.join(data_dir, prepared_vocab_file)
        self.fields = {}
        self.filter_pred = None
        self.sort_fn = None
        self.data = None

    def load(self):
        """
        load
        """
        if not (os.path.exists(self.prepared_data_file) or os.path.exists(self.prepared_vocab_file)):
            self.build()
        elif os.path.exists(self.prepared_vocab_file) and not os.path.exists(self.prepared_data_file):
            self.load_vocab(self.prepared_vocab_file)
            self.build()
        else:
            self.load_vocab(self.prepared_vocab_file)
            self.load_data(self.prepared_data_file)

        self.padding_idx = self.TGT.stoi[self.TGT.pad_token]

    def reload(self, data_type='test'):
        """
        reload
        """
        data_file1 = os.path.join(self.data_dir, self.data_prefix + "." + 'test1')
        data_file2 = os.path.join(self.data_dir, self.data_prefix + "." + 'test2')
        data_raw1,data_raw2 = self.read_data_multitask(data_file1, data_file2,data_type="test")
        data_examples1 = self.build_examples(data_raw1)
        data_examples2 = self.build_examples(data_raw2)
        self.data[data_type] = Dataset((data_examples1,data_examples2))

        print("Number of examples:",
              " ".join("{}-{}".format(k.upper(), len(v)) for k, v in self.data.items()))

    def load_data(self, prepared_data_file=None):
        """
        load_data
        """
        prepared_data_file = prepared_data_file or self.prepared_data_file
        print("Loading prepared data from {} ...".format(prepared_data_file))
        data = torch.load(prepared_data_file)
        print(len(data['train']))
        print(len(data['valid']))
        print(len(data['valid']))
    
        self.data = {"train": Dataset(data['train']),
                     "valid": Dataset(data["valid"]),
                     "test": Dataset(data["test"])}

        print("Number of examples:",
              " ".join("{}-{}".format(k.upper(), len(v)) for k, v in self.data.items()))

    def load_vocab(self, prepared_vocab_file):
        """
        load_vocab
        """
        prepared_vocab_file = prepared_vocab_file or self.prepared_vocab_file
        print("Loading prepared vocab from {} ...".format(prepared_vocab_file))
        vocab_dict = torch.load(prepared_vocab_file)

        for name, vocab in vocab_dict.items():
            if name in self.fields:#self.fields = {'src': self.SRC, 'tgt': self.TGT, 'cue': self.CUE}
                self.fields[name].load_vocab(vocab)
        print("Vocabulary size of fields:",
              " ".join("{}-{}".format(name.upper(), field.vocab_size) 
                for name, field in self.fields.items() 
                    if isinstance(field, TextField)))

    def read_data(self, data_file, data_type=None):
        """
        Returns
        -------
        data: ``List[Dict]``
        """
        raise NotImplementedError

    def build_vocab(self, data):
        """
        Args
        ----
        """
        #第一阶段data=[{'src':['query1','query2','query3'], 'tgt': 'response', 'cue':'persona1'},{...},...]
        #第二阶段data=[{'src':'query', 'tgt': 'response', 'cue':['persona1','persona2',...],'label':'2','index':'14 15 17'},{...},...]
        #第一阶段self.fields = {'src': self.SRC, 'tgt': self.TGT, 'cue': self.CUE}
        #第二阶段self.fields = {'src': self.SRC, 'tgt': self.TGT, 'cue': self.CUE, 'label': self.LABEL, 'index': self.INDEX}
        field_data_dict = {}
        for name in data[0].keys():
            field = self.fields.get(name) 
            if isinstance(field, TextField):
                xs = [x[name] for x in data]
                if field not in field_data_dict:
                    field_data_dict[field] = xs
                else:
                    field_data_dict[field] += xs
        vocab_dict = {}
        for name, field in self.fields.items():
            if field in field_data_dict:
                print("Building vocabulary of field {} ...".format(name.upper()))
                if field.vocab_size == 0:
                    field.build_vocab(field_data_dict[field],
                                      min_freq=self.min_freq,
                                      max_size=self.max_vocab_size)
                vocab_dict[name] = field.dump_vocab()
        return vocab_dict

    def build_examples(self, data):
        """
        Args
        ----
        第一阶段self.fields = {'src': self.SRC, 'tgt': self.TGT, 'cue': self.CUE}
        第二阶段self.fields = {'src': self.SRC, 'tgt': self.TGT, 'cue': self.CUE, 'label': self.LABEL, 'index': self.INDEX}
        """
        
        #第一阶段data=[{'src':['query1','query2','query3'], 'tgt': 'response', 'cue':'persona'},{...},...]
        #第二阶段data=[{'src':'query', 'tgt': 'response', 'cue':['persona1','persona2',...],'label':'2','index':'14 15 17'},{...},...]
        examples = []
        for raw_data in tqdm(data):
            example = {}
            for name, strings in raw_data.items():
                example[name] = self.fields[name].numericalize(strings)
            examples.append(example) 
        if self.sort_fn is not None:
            print("Sorting examples ...")
            examples = self.sort_fn(examples)
        return examples   

    def build(self):
        """
        build
        """
        print("Start to build corpus!")
        train_file1 = os.path.join(self.data_dir, self.data_prefix + ".train1")
        valid_file1 = os.path.join(self.data_dir, self.data_prefix + ".dev1")
        test_file1 = os.path.join(self.data_dir, self.data_prefix + ".test1")
        train_file2 = os.path.join(self.data_dir, self.data_prefix + ".train2")
        valid_file2 = os.path.join(self.data_dir, self.data_prefix + ".dev2")
        test_file2 = os.path.join(self.data_dir, self.data_prefix + ".test2")

        print("Reading data ...")
       
        train_raw1, train_raw2 = self.read_data_multitask(train_file1, train_file2, data_type="train")
        valid_raw1, valid_raw2 = self.read_data_multitask(valid_file1,valid_file2, data_type="valid")
        test_raw1, test_raw2= self.read_data_multitask(test_file1,test_file2, data_type="test")#
        

        
        if not os.path.exists(self.prepared_vocab_file):
            vocab = self.build_vocab(train_raw2)
            print("Saving prepared vocab ...")
            torch.save(vocab, self.prepared_vocab_file)
            print("Saved prepared vocab to '{}'".format(self.prepared_vocab_file))
        
        print("Building TRAIN examples ...")
        train_data1 = self.build_examples(train_raw1) 
        train_data2 = self.build_examples(train_raw2)
        '''
        train_data=[{'src':[5,10,36,99],[33,21,56],[9,26,66,38,47]'tgt':[22,45,33,98,101],'cue':[25,35,66]},
                    {},
                    {},...]
        '''
        print("Building VALID examples ...")
        valid_data1 = self.build_examples(valid_raw1)
        valid_data2 = self.build_examples(valid_raw2)
        print("Building TEST examples ...")
        test_data1 = self.build_examples(test_raw1)
        test_data2 = self.build_examples(test_raw2)


        data = {"train": (train_data1,train_data2),
                "valid": (valid_data1,valid_data2),
                "test": (test_data1,test_data2)}

        print("Saving prepared data ...")
        torch.save(data, self.prepared_data_file)
        print("Saved prepared data to '{}'".format(self.prepared_data_file))


    def create_batches(self, batch_size, data_type="train",
                       shuffle=False, device=None):
        """
        create_batches
        """
        try:
            data = self.data[data_type] 
            data_loader = data.create_batches(batch_size, shuffle, device) 
            return data_loader
        except KeyError:
            raise KeyError("Unsported data type: {}!".format(data_type))

    def transform(self, data_file, batch_size,
                  data_type="test", shuffle=False, device=None):
        """
        Transform raw text from data_file to Dataset and create data loader.
        """
        raw_data = self.read_data(data_file, data_type=data_type)
        examples = self.build_examples(raw_data)
        data = Dataset(examples)
        data_loader = data.create_batches(batch_size, shuffle, device)
        return data_loader


class SrcTgtCorpus(Corpus):
    """
    SrcTgtCorpus
    """
    def __init__(self,
                 data_dir,
                 data_prefix,
                 min_freq=0,
                 max_vocab_size=None,
                 min_len=0,
                 max_len=100,
                 embed_file=None,
                 share_vocab=False):
        super(SrcTgtCorpus, self).__init__(data_dir=data_dir,
                                           data_prefix=data_prefix,
                                           min_freq=min_freq,
                                           max_vocab_size=max_vocab_size)
        self.min_len = min_len
        self.max_len = max_len
        self.share_vocab = share_vocab

        self.SRC = TextField(tokenize_fn=tokenize,
                             embed_file=embed_file)
        if self.share_vocab:
            self.TGT = self.SRC
        else:
            self.TGT = TextField(tokenize_fn=tokenize,
                                 embed_file=embed_file)

        self.fields = {'src': self.SRC, 'tgt': self.TGT}

        def src_filter_pred(src):
            """
            src_filter_pred
            """
            return min_len <= len(self.SRC.tokenize_fn(src)) <= max_len

        def tgt_filter_pred(tgt):
            """
            tgt_filter_pred
            """
            return min_len <= len(self.TGT.tokenize_fn(tgt)) <= max_len

        self.filter_pred = lambda ex: src_filter_pred(ex['src']) and tgt_filter_pred(ex['tgt'])

    def read_data(self, data_file, data_type="train"):
        """
        read_data
        """
        data = []
        filtered = 0
        with open(data_file, "r", encoding="utf-8") as f:
            for line in f:
                src, tgt = line.strip().split('\t')[:2]
                data.append({'src': src, 'tgt': tgt})

        filtered_num = len(data)
        if self.filter_pred is not None:
            data = [ex for ex in data if self.filter_pred(ex)]
        filtered_num -= len(data)
        print(
            "Read {} {} examples ({} filtered)".format(len(data), data_type.upper(), filtered_num))
        return data


class PersonaCorpus(Corpus):
    """
    PersonaCorpus
    """
    def __init__(self,
                 data_dir,
                 data_prefix,
                 min_freq=0,
                 max_vocab_size=None,
                 min_len=0,
                 max_len=100,
                 embed_file=None,
                 share_vocab=False,
                 with_label=False):
        super(PersonaCorpus, self).__init__(data_dir=data_dir,
                                              data_prefix=data_prefix,
                                              min_freq=min_freq,
                                              max_vocab_size=max_vocab_size)
        self.min_len = min_len
        self.max_len = max_len
        self.share_vocab = share_vocab
        self.with_label = with_label

        self.SRC = TextField(tokenize_fn=tokenize,
                             embed_file=embed_file)
        # self.LABEL = NumberField(dtype = float)
        # self.LABEL = NumberField(sequential=True, dtype = int)

        if self.share_vocab:
            self.TGT = self.SRC
            self.CUE = self.SRC
        else:
            self.TGT = TextField(tokenize_fn=tokenize,
                                 embed_file=embed_file)
            self.CUE = TextField(tokenize_fn=tokenize,
                                 embed_file=embed_file)

        if self.with_label:
            self.LABEL = NumberField(sequential=False, dtype = int)
            self.INDEX = NumberField(sequential=True, dtype = int)
            self.fields = {'src': self.SRC, 'tgt': self.TGT, 'cue': self.CUE, 'label': self.LABEL, 'index': self.INDEX}
        else:
            self.fields = {'src': self.SRC, 'tgt': self.TGT, 'cue': self.CUE }
            

        def src_filter_pred(src):
            """
            src_filter_pred
            """
            for sen in src:
                if not (min_len <= len(self.SRC.tokenize_fn(sen)) <= max_len):
                    return False
                else:
                    return True

        def tgt_filter_pred(tgt):
            """
            tgt_filter_pred
            """
            return min_len <= len(self.TGT.tokenize_fn(tgt)) <= max_len

        self.filter_pred = lambda ex: src_filter_pred(ex['src']) and tgt_filter_pred(ex['tgt'])
    def read_data(self, data_file, data_type="train"):
        """
        read_data
        """
        data = []
        with open(data_file, "r", encoding="utf-8") as f:
            for line in f:
                # print(self.with_label)
                if self.with_label:
                    query, response, personas, persona_label, key_index = line.strip().split('\t')[:5]
                    filter_personas = []
                    for sent in personas.split('**'):
                        filter_personas.append(' '.join(sent.split()[:self.max_len]))
                    index = key_index

                    data.append({'src': query, 'tgt': response, 'cue': filter_personas, 'label': persona_label, 'index': index})
                else:
                    queries, response, persona = line.strip().split('\t')[:3]
                    src=queries.split('**')
                    # filter_persona = ' '.join(persona.split()[:self.max_len])
                    filter_persona = persona
                    data.append({'src': src, 'tgt': response, 'cue': filter_persona})

        filtered_num = len(data)
        if self.filter_pred is not None:
            data = [ex for ex in data if self.filter_pred(ex)]
        filtered_num -= len(data)
        print(
            "Read {} {} examples ({} filtered)".format(len(data), data_type.upper(), filtered_num))
        return data

    def read_data_multitask(self, data_file1, data_file2, data_type="train"):
        """
        read_data
        """
        data1 = []
        data2 = []
        with open(data_file2, "r", encoding="utf-8") as f:
            for line in f:
                # print(self.with_label)
                query, response, personas, persona_label, key_index = line.strip().split('\t')[:5]
                filter_personas = []
                for sent in personas.split('**'):
                    filter_personas.append(' '.join(sent.split()[:self.max_len]))
                index = key_index

                data2.append({'src': query, 'tgt': response, 'cue': filter_personas, 'label': persona_label, 'index': index})
        filtered_num = len(data2)
        if self.filter_pred is not None:
            data2 = [ex for ex in data2 if self.filter_pred(ex)]
        filtered_num -= len(data2)
        print(
            "Read {} {} examples ({} filtered)".format(len(data2), data_type.upper()+'task2', filtered_num))

        with open(data_file1, "r", encoding="utf-8") as f:
            for line in f:
                queries, response, persona = line.strip().split('\t')[:3]
                src=queries.split('**')
                # filter_persona = ' '.join(persona.split()[:self.max_len])
                filter_persona = persona
                data1.append({'src': src, 'tgt': response, 'cue': filter_persona})
        filtered_num = len(data1)
        if self.filter_pred is not None:
            data1 = [ex for ex in data1 if self.filter_pred(ex)]
        filtered_num -= len(data1)
        print(
            "Read {} {} examples ({} filtered)".format(len(data1), data_type.upper()+'task1', filtered_num))
        
        return data1, data2
