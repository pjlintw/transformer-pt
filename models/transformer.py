
from .utils import create_transformer_masks
from .encoder import TransformerEncoder
from .decoder import TransformerDecoder

import math
import torch
import torch.nn as nn
import torch.nn.functional as F

class Transformer(nn.Module):
    def __init__(self, 
                 num_layers,
                 d_model, num_head,
                 intermediate_dim,
                 input_vocab_size,
                 target_vocab_size,
                 src_max_len,
                 tgt_max_len,
                 padding_idx,
                 shared_emb_layer=None, # Whether use embeeding layer from encoder
                 rate=0.1):
        super(Transformer, self).__init__()
        self.d_model = d_model
        self.pad_idx = padding_idx

        # (vocab_size, emb_dim)
        self.embedding_layer = nn.Embedding(input_vocab_size, d_model)
    
        self.encoder = TransformerEncoder(num_layers, d_model, num_head,
                                          intermediate_dim,
                                          input_vocab_size,
                                          src_max_len, 
                                          rate)

        if shared_emb_layer is True:
            self.shared_emb_layer = self.embedding_layer
        else:
            self.shared_emb_layer = shared_emb_layer
        # print(self.shared_emb_layer)
        self.decoder = TransformerDecoder(num_layers, d_model, num_head,
                                         intermediate_dim,
                                         target_vocab_size,
                                         tgt_max_len,
                                         self.shared_emb_layer,  # share embedding
                                         rate)
        self.final_layer = nn.Linear(d_model, target_vocab_size)
    
        
    def forward(self, src, tgt, training, enc_padding_mask,
                look_ahead_mask, dec_padding_mask, cuda):
        """Forward propagate for transformer.
        
        Args:
          src: (batch_size, src_max_len)
            
        """
        # Mapping
        src = self.embedding_layer(src)
        src = torch.mul(src, (self.d_model**(1/2)))

        # (batch_size, inp_seq_len, d_model)
        enc_out = self.encoder(src, training, enc_padding_mask, gpu=cuda) #.cuda()

        # if cuda:
        #     enc_out = enc_out.cuda()
        # print("type of decoder input", type(tgt))
        # print("decoder input", tgt)
        # (batch_size, tgt_seq_len, d_model)
        dec_output, dec_attn = self.decoder(x=tgt, 
                                            enc_output=enc_out, 
                                            training=training, 
                                            look_ahead_mask=look_ahead_mask,
                                            padding_mask=dec_padding_mask,
                                            gpu=cuda)

        # (batch_size, tgt_seq_len, target_vcoab_size)
        final_output = self.final_layer(dec_output)

        return final_output, dec_attn


    def sample(self, inp, max_len, sos_idx, eos_idx, src_pad_idx, tgt_pad_idx, device, temperature=None, decode_strategy="greedy"):
        """Forward propagate for transformer.
        
        Args:
          inp:
          max_len:
          temperature
          sos_idx
          eos_idx

        Returns:
          out: (batch_size, max_len)
        """
        if torch.is_tensor(inp):
            pass
        else:
            inp = torch.tensor(inp, device=device)

        #if cuda:
        #    inp = inp.cuda()

        # Gumbel-Softmax tricks
        batch_size = inp.shape[0]
        #sampled_ids = torch.zeros(batch_size, max_len).type(torch.LongTensor)

        # (batch_size, 1)
        # Create a tensor on CPU by default
        output = torch.tensor([sos_idx]*batch_size).unsqueeze(1)
        if device:
            output=output.to(device)
        assert output.shape[-1] == 1 
        
        for i in range(max_len-1):
            # print(output)

            # enc_pad_mask, combined_mask, dec_pad_mask
            enc_padding_mask, combined_mask, dec_padding_mask = create_transformer_masks(inp,
                                                                                         output, 
                                                                                         src_pad_idx=src_pad_idx,
                                                                                         tgt_pad_idx=tgt_pad_idx,
                                                                                         device=device)
            # predictions.shape == (batch_size, seq_len, vocab_size)
            predictions, _ = self.forward(inp,     # (bathc_size, 1)
                                          output,  # (batch_size, 1-TO-MAXLEN)
                                          False,
                                          enc_padding_mask,
                                          combined_mask,
                                          dec_padding_mask,
                                          cuda=device)
            
            # Select the last word from the seq_len dimension
            # (batch_size, 1, vocab_size) to (batch_size, voacb_size) 
            predictions = predictions[: ,-1:, :].squeeze() 
            # print("preds", predictions.shape)

            if decode_strategy == "greedy":
                predicted_idx = torch.argmax(predictions, dim=-1).unsqueeze(1)
                # print(predicted_idx.shape)
                # print(predicted_idx)
            elif decode_strategy == "gumbel":
                # (batch_size, 1)
                # assert inp.shape[-1] = 1
                gumbel_distribution = gumbel_softmax_sample(predictions, temperature,gpu=cuda)
                # (batch_size, vocab_size)
                # print("gumbel", gumbel_distribution.shape)

                # (batch_sizes) to (bathc_size, 1)
                predicted_idx = torch.argmax(gumbel_distribution, dim=-1).unsqueeze(1)

            # print("pred idx", predicted_idx.shape)
            output = torch.cat((output, predicted_idx), 1)
            # Update along with col
            #sampled_ids[:,i] = predicted_idx.squeeze()
        #print(sampled_ids==output[:,1:])
        return output


    def evaluate(self, dataset, args, pad_idx, acc_fn):
        """Perform evaluate."""
        self.eval()
        
        total_loss = 0
        total_accuracy = 0
        step = 0
        loss_fn = nn.CrossEntropyLoss(ignore_index=pad_idx)
        for features_dict in dataset:
            # Encoder input: (batch_size, seq_len)
            src = features_dict["source_ids"]
            # Decoder input and target: (batch_size, seq_len-1)
            tgt_inp = features_dict["target_input"]
            tgt_out = features_dict["target_output"]
            
            enc_padding_mask = features_dict["enc_padding_mask"]
            combined_mask = features_dict["combined_mask"]
            dec_padding_mask =features_dict["dec_padding_mask"]
            
            logits, attn = self.forward(src=src,
                                        tgt=tgt_inp,
                                        training=False,
                                        enc_padding_mask=enc_padding_mask,
                                        look_ahead_mask=combined_mask,
                                        dec_padding_mask=dec_padding_mask,
                                        cuda=args.gpu)

            two_d_logits = logits.reshape(-1, logits.shape[-1])
            loss = loss_fn(two_d_logits, tgt_out.reshape(-1))

            pred = logits.argmax(-1)
            acc = acc_fn(real=tgt_out,
                         pred=pred,
                         pad_idx=pad_idx)
            total_loss += loss.item()
            total_accuracy += acc
            step+= 1
        avg_loss = total_loss/ step
        avg_acc = total_accuracy / step
        return avg_loss, avg_acc

def sample_gumbel(shape, eps=1e-20, device=None):
    """Sample from Gumbel(0, 1)"""
    if device:
        device="cuda"
    # The drawn nosie is created by default in CPU
    noise = torch.rand(shape, device=device)
    return -torch.log(-torch.log(noise+eps)+eps)


def gumbel_softmax_sample(logits, temperature, gpu):
    """Sample from Gumbel softmax distribution.
    Reference:
        1. Gumbel distribution: https://en.wikipedia.org/wiki/Gumbel_distribution
        2. Inverse Tranform Sampling: https://en.wikipedia.org/wiki/Inverse_transform_sampling
    """
    y = logits + sample_gumbel(shape=logits.shape, device=gpu)
    return nn.functional.softmax(y/temperature, dim=-1)


if __name__ == "__main__":
    transf = Transformer(2,512,8,2048,8500, 8000,10000,6000, -100, None)

    i = torch.randint(0, 200, (64,38))  
    tgt_i = torch.randint(0,200, (64, 36))

    output, attn = transf(i,
                          tgt_i,
                          training=False,
                          enc_padding_mask=None,
                          look_ahead_mask=None,
                          dec_padding_mask=None)

    print(output.shape)