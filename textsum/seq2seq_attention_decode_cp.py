"""Module for decoding."""

import os
import time

import beam_search
import data
from six.moves import xrange
import tensorflow as tf


import batch_reader


FLAGS = tf.app.flags.FLAGS
tf.app.flags.DEFINE_integer('max_decode_steps', 1000000,
                            'Number of decoding steps.')
tf.app.flags.DEFINE_integer('decode_batches_per_ckpt', 1,
                            'Number of batches to decode before restoring next '
                            'checkpoint')


class DecodeIO(object):
    """Writes the decoded and references to RKV files for Rouge score.

        See nlp/common/utils/internal/rkv_parser.py for detail about rkv file.
    """

    def __init__(self, outdir):
        pass

    def Write(self, article, reference, decode):
        """Writes the reference and decoded outputs to RKV files.

        Args:
            reference: The human (correct) result.
            decode: The machine-generated result
        """
        print('--------------------------------------------------')
        print('[輸入的Behavior Context]\n%s\n' % article)
        print('[真實人類的Description]\n%s\n' % reference)
        print('[機器產生的Description]\n%s\n' % decode)
        print('--------------------------------------------------')


class BSDecoder(object):
    """Beam search decoder."""

    def __init__(self, model, hps, vocab, to_build_grapth):
        """Beam search decoding.

        Args:
            model: The seq2seq attentional model.
            batch_reader: The batch data reader.
            hps: Hyperparamters.
            vocab: Vocabulary
        """
        self._model = model
        if to_build_grapth:
            self._model.build_graph()
        # 這是batch_reader.Batcher物件，只使用.NextBatch()函式
        self._batch_reader = batch_reader.Batcher(
                FLAGS.data_path, vocab, hps, FLAGS.article_key,
                FLAGS.abstract_key, FLAGS.max_article_sentences,
                FLAGS.max_abstract_sentences, bucketing=FLAGS.use_bucketing,
                truncate_input=FLAGS.truncate_input)
        self._hps = hps
        self._vocab = vocab
        self._saver = tf.train.Saver()
        self._decode_io = DecodeIO(FLAGS.decode_dir)

    def DecodeLoop(self):
        """Decoding loop for long running process."""
        sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True))
        self._Decode(self._saver, sess)

    def _Decode(self, saver, sess):
        """Restore a checkpoint and decode it.

        Args:
            saver: Tensorflow checkpoint saver.
            sess: Tensorflow session.
        Returns:
            If success, returns true, otherwise, false.
        """
        ckpt_state = tf.train.get_checkpoint_state(FLAGS.log_root)
        if not (ckpt_state and ckpt_state.model_checkpoint_path):
            tf.logging.info('No model to decode yet at %s', FLAGS.log_root)
            return False

        tf.logging.info('checkpoint path %s', ckpt_state.model_checkpoint_path)
        ckpt_path = os.path.join(
                FLAGS.log_root, os.path.basename(ckpt_state.model_checkpoint_path))
        tf.logging.info('renamed checkpoint path %s', ckpt_path)
        saver.restore(sess, ckpt_path)

        (article_batch, _, _, article_lens, _, _, origin_articles,
         origin_abstracts) = self._batch_reader.NextBatch()
        for i in xrange(self._hps.batch_size):
            bs = beam_search.BeamSearch(
                    self._model, self._hps.batch_size,
                    self._vocab.WordToId(data.SENTENCE_START),
                    self._vocab.WordToId(data.SENTENCE_END),
                    self._hps.dec_timesteps)

            article_batch_cp = article_batch.copy()
            article_batch_cp[:] = article_batch[i:i+1]
            article_lens_cp = article_lens.copy()
            article_lens_cp[:] = article_lens[i:i+1]
            best_beam = bs.BeamSearch(sess, article_batch_cp, article_lens_cp)[0]
            decode_output = [int(t) for t in best_beam.tokens[1:]]
            self._DecodeBatch(
                    origin_articles[i], origin_abstracts[i], decode_output)
            break

    def _DecodeBatch(self, article, abstract, output_ids):
        """Convert id to words and writing results.

        Args:
            article: The original article string.
            abstract: The human (correct) abstract string.
            output_ids: The abstract word ids output by machine.
        """
        decoded_output = ' '.join(data.Ids2Words(output_ids, self._vocab))
        end_p = decoded_output.find(data.SENTENCE_END, 0)
        if end_p != -1:
            decoded_output = decoded_output[:end_p]
        tf.logging.info('article:  %s', article)
        tf.logging.info('abstract: %s', abstract)
        tf.logging.info('decoded:  %s', decoded_output)
        self._decode_io.Write(article, abstract, decoded_output.strip())
