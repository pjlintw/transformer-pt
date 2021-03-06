#!/bin/sh
# Run `run_trainer.py` script

for num_layer in 2 4 8;
do
	for dims in 64 128 256 512;
	do
		for num_head in 1 4 8 16 32; # 1 4 8 16 32
		do
			echo "Execute run_trainer.py layers=${num_layer}, dims=${dims}, heads=${num_head}"
			python run_trainer.py \
				--output_dir results/subword_epoch-15/L-${num_layer}_D-${dims}_H-${num_head} \
				--source_vocab data/de-en/subword/source.vocab \
				--target_vocab data/de-en/subword/target.vocab \
				--tf_layers $num_layer \
			 	--tf_dims $dims \
				--tf_heads $num_head \
				--dataset_script php-de-en_subword.py \
				--max_seq_length 20 \
				--batch_size 64 \
				--do_train True \
				--do_eval True \
				--do_predict True \
				--mle_epochs 15
		 done
	done
done
