import torch
import torch.nn as nn

from torch.nn.utils.rnn import pack_padded_sequence
from torch.nn.utils.rnn import pad_packed_sequence


class ContextEncoder(nn.Module):
    """
    A GRU recurrent neural network encoder.
    """
    def __init__(self,
                 input_size,
                 hidden_size,
                 embedder=None,
                 num_layers=1,
                 bidirectional=True,
                 dropout=0.0):
        super(ContextEncoder, self).__init__()

        num_directions = 2 if bidirectional else 1
        assert hidden_size % num_directions == 0
        rnn_hidden_size = hidden_size // num_directions

        self.input_size = input_size
        self.hidden_size = hidden_size
        self.rnn_hidden_size = rnn_hidden_size
        self.embedder = embedder
        self.num_layers = num_layers
        self.bidirectional = bidirectional
        self.dropout = dropout
        self.rnn = nn.GRU(input_size=self.input_size,
                          hidden_size=self.rnn_hidden_size,
                          num_layers=self.num_layers,
                          batch_first=True,
                          dropout=self.dropout if self.num_layers > 1 else 0,
                          bidirectional=self.bidirectional)

    def forward(self, inputs, hidden=None):
        """
        forward
        """
        #inputs:(batch_size, 1, 2*rnn_hidden_size)**src去头去尾
        #lengths:(batch_size)
        #hidden:(num_layers , batch_size , 2*rnn_hidden_size)
        if isinstance(inputs, tuple):
            inputs, lengths = inputs
        else:
            inputs, lengths = inputs, None

        if self.embedder is not None:
            rnn_inputs = self.embedder(inputs)
        else:
            rnn_inputs = inputs
        #rnn_inputs:(batch_size, 1, 2*rnn_hidden_size)
        batch_size = rnn_inputs.size(0)

        hidden = self.inv_bridge_bidirectional_hidden(hidden)#(2*num_layers ,batch_size, rnn_hidden_size)
        
        if lengths is not None:#根据长度重排序,并去除无效长度的样本
            num_valid = lengths.gt(0).int().sum().item()
            sorted_lengths, indices = lengths.sort(descending=True)
            rnn_inputs = rnn_inputs.index_select(0, indices)[:num_valid].contiguous()

            if hidden is not None:
                output_hidden = hidden.index_select(1, indices).contiguous()
                valid_hidden = hidden.index_select(1, indices)[:, :num_valid].contiguous()
                


        outputs, last_hidden = self.rnn(rnn_inputs, valid_hidden)
        #outputs:(batch_size, max_len-2, 2*rnn_hidden_size)
        #last_hidden:(2*num_layers ,num_valid, rnn_hidden_size)

        if lengths is not None:
            if num_valid < batch_size:#填补无效长度的样本
                zeros = outputs.new_zeros(
                    batch_size - num_valid, outputs.size(1), self.hidden_size)
                outputs = torch.cat([outputs, zeros], dim=0)
                feak_hidden = output_hidden[:, num_valid:]#(2*num_layers , batch_size - num_valid , rnn_hidden_size)
                last_hidden = torch.cat([last_hidden, feak_hidden], dim=1)

            _, inv_indices = indices.sort()
            outputs = outputs.index_select(0, inv_indices).contiguous()#将上述排序撤回
            last_hidden = last_hidden.index_select(1, inv_indices).contiguous()
        if self.bidirectional:
            last_hidden = self._bridge_bidirectional_hidden(last_hidden)#last_hidden:(num_layers, batch_size, 2*rnn_hidden_size)

        return outputs, last_hidden

    def _bridge_bidirectional_hidden(self, hidden):
        """
        the bidirectional hidden is (num_layers * num_directions, batch_size, hidden_size)
        we need to convert it to (num_layers, batch_size, num_directions * hidden_size)
        """
        num_layers = hidden.size(0) // 2
        _, batch_size, hidden_size = hidden.size()
        return hidden.view(num_layers, 2, batch_size, hidden_size)\
            .transpose(1, 2).contiguous().view(num_layers, batch_size, hidden_size * 2)
    def inv_bridge_bidirectional_hidden(self, hidden):
        """
        the bidirectional hidden is (num_layers * num_directions, batch_size, hidden_size)
        we need to convert it to (num_layers, batch_size, num_directions * hidden_size)
        """
        hidden_size = hidden.size(2) // 2
        num_layers, batch_size, _ = hidden.size()
        return hidden.view(num_layers,batch_size,2,hidden_size)\
            .transpose(2, 1).contiguous().view(num_layers*2, batch_size, hidden_size)