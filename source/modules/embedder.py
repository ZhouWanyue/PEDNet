#!/usr/bin/env python
# -*- coding: utf-8 -*-
################################################################################
#
# Copyright (c) 2019 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
File: source/encoders/embedder.py
"""

import torch
import torch.nn as nn


class Embedder(nn.Embedding):
    """
    Embedder
    """
    def load_embeddings(self, embeds, scale=0.05):
        """
        load_embeddings
        """
        #assert（断言）用于判断一个表达式，在表达式条件为 false 的时候触发异常
        #num_embeddings是实例化embedder时的参数，可在seq2seq模型的结构中看到，num_embeddings是词表的长度
        assert len(embeds) == self.num_embeddings#[[* dim],[* dim],[* dim],[* dim]…………………………],shape:（len(vocab)*300), embed_file中没有的单词embedding会设为0。


        embeds = torch.tensor(embeds) 
        num_known = 0
        for i in range(len(embeds)):
            if len(embeds[i].nonzero()) == 0:   #如果embeds[i]中全都是0
                nn.init.uniform_(embeds[i], -scale, scale)
            else:
                num_known += 1
        self.weight.data.copy_(embeds)
        print("{} words have pretrained embeddings".format(num_known),
              "(coverage: {:.3f})".format(num_known / self.num_embeddings))
