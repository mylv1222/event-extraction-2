import numpy as np
import time, datetime, os
import tensorflow as tf
from sklearn.metrics import classification_report, precision_score, recall_score, accuracy_score
from Dataset_Trigger import Dataset_Trigger as Dataset

from Config import HyperParams_Tri_classification as hp

"""
Trigger Classification is based on the previous argument classification task's code.
Reference code link is https://github.com/zhangluoyang/cnn-for-auto-event-extract
"""


class Model():
    def __init__(self,
                 sentence_length=30,
                 num_labels=10,
                 windows=3,
                 vocab_size=2048,
                 pos_tag_max_size = 60,
                 word_embedding_size=100,
                 pos_embedding_size=10,
                 filter_sizes=[3, 4, 5],
                 filter_num=200,
                 batch_size=10,
                 embed_matrx=None
                 ):

        tf_version_checker = int(tf.__version__.split('.')[0])

        """
        :param sentence_length
        :param num_labels
        :param windows
        :param vocab_size
        :param word_embedding_size
        :param pos_embedding_size
        :param filter_sizes
        :param filter_num
        """

        # TODO: Check whether batch size can determined arbitrary in <1.0.0 version.
        batch_size = None
        # [batch_size, sentence_length]
        input_x = tf.placeholder(tf.int32, shape=[batch_size, sentence_length], name="input_x")
        self.input_x = input_x
        # [batch_size, num_labels]
        input_y = tf.placeholder(tf.float32, shape=[batch_size, num_labels], name="input_y")
        self.input_y = input_y

        # input_y_weights = tf.placeholder(tf.float32, shape=[batch_size], name="input_y_weights")

        # input_pos_tag = tf.placeholder(tf.int32, shape=[batch_size, sentence_length], name="input_pos_tag")
        # self.input_pos_tag = input_pos_tag

        # argument candidates distance vector
        # example: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
        input_c_pos = tf.placeholder(tf.int32, shape=[batch_size, sentence_length], name="input_c_pos")
        self.input_c_pos = input_c_pos

        dropout_keep_prob = tf.placeholder(tf.float32, name="dropout_keep_prob")
        self.dropout_keep_prob = dropout_keep_prob

        with tf.name_scope("word_embedding_layer"):
            # [vocab_size, embedding_size]

            # TODO: Word2Vec lookup table
            if embed_matrx is None:  # use randomly initialized matrix as word embedding
                W_text = tf.Variable(tf.random_normal(shape=[vocab_size, word_embedding_size], mean=0.0, stddev=0.5), name="word_table")
            else:  # pre-trained word embedding matrix
                W_text = tf.Variable(embed_matrx, trainable=False, dtype=tf.float32, name='word_embedding')
            input_word_vec = tf.nn.embedding_lookup(W_text, input_x)

            # Pos_tag = tf.Variable(
            #     tf.random_normal(shape=[pos_tag_max_size, pos_embedding_size], mean=0.0, stddev=0.5),
            #     name="input_pos_tag_table")
            # input_pos_tag_vec = tf.nn.embedding_lookup(Pos_tag, input_pos_tag)

            input_c_pos_c = input_c_pos + (sentence_length - 1)
            Can_pos = tf.Variable(
                tf.random_normal(shape=[2 * (sentence_length - 1) + 1, pos_embedding_size], mean=0.0, stddev=0.5),
                name="candidate_pos_table")
            input_c_pos_vec = tf.nn.embedding_lookup(Can_pos, input_c_pos_c)

            # The feature of the distance and the word features of the sentence constitute a collated feature as an input to the convolutional neural network.
            # [batch_size, sentence_length, word_embedding_size+2*pos_size]

            # [input_word_vec, input_c_pos_vec, input_pos_tag_vec]
            input_sentence_vec = tf.concat([input_word_vec, input_c_pos_vec], 2)
            # CNN supports 4d input, so increase the one-dimensional vector to indicate the number of input channels.
            input_sentence_vec_expanded = tf.expand_dims(input_sentence_vec, -1)
        pooled_outputs = []
        for i, filter_size in enumerate(filter_sizes):
            with tf.name_scope('conv-maxpool-%s' % filter_size):
                # The current word and context of the sentence feature considered here
                # when using pos_tag: [filter_size, word_embedding_size +  2 * pos_embedding_size, 1, filter_num]
                filter_shape = [filter_size, word_embedding_size +  pos_embedding_size, 1, filter_num]
                W = tf.Variable(tf.truncated_normal(filter_shape, stddev=0.1), name="W")
                b = tf.Variable(tf.constant(0.1, shape=[filter_num]), name="b")
                # Convolution operation
                conv = tf.nn.conv2d(
                    input_sentence_vec_expanded,
                    W,
                    strides=[1, 1, 1, 1],
                    padding="VALID",
                    name="conv")
                h = tf.nn.relu(tf.nn.bias_add(conv, b), name="relu")
                # Maximize pooling
                pooled = tf.nn.max_pool(
                    h,
                    ksize=[1, sentence_length - filter_size + 1, 1, 1],
                    strides=[1, 1, 1, 1],
                    padding='VALID',
                    name="pool")
                pooled_outputs.append(pooled)

        num_filters_total = filter_num * len(filter_sizes)
        # The number of all filters used (number of channels output)
        h_pool = tf.concat(pooled_outputs, 3)
        # Expand to the next level classifier
        h_pool_flat = tf.reshape(h_pool, [-1, num_filters_total])
        lexical_vec = tf.reshape(input_word_vec, shape=(-1, sentence_length * word_embedding_size))
        # Combine lexical level features and sentence level features
        # [batch_size, num_filters_total] + [batch_size, sentence_length*word_embedding_size]
        all_input_features = tf.concat([lexical_vec, h_pool_flat], 1)
        # The overall classifier goes through a layer of dropout and then into softmax
        with tf.device('/cpu:0'), tf.name_scope('dropout'):
            all_features = tf.nn.dropout(all_input_features, dropout_keep_prob)

        with tf.name_scope('output'):
            W = tf.Variable(tf.truncated_normal([num_filters_total + sentence_length * word_embedding_size, num_labels], stddev=0.1), name="W")
            b = tf.Variable(tf.constant(0.1, shape=[num_labels]), name="b")
            scores = tf.nn.xw_plus_b(all_features, W, b, name="scores")
            predicts = tf.arg_max(scores, dimension=1, name="predicts")
            self.scores = scores
            self.predicts = predicts

        with tf.name_scope('loss'):
            entropy = tf.nn.softmax_cross_entropy_with_logits(labels=input_y, logits=scores)
            loss = tf.reduce_mean(entropy)
            self.loss = loss

        with tf.name_scope("accuracy"):
            correct = tf.equal(predicts, tf.argmax(input_y, 1))
            accuracy = tf.reduce_mean(tf.cast(correct, "float"), name="accuracy")
            self.accuracy = accuracy
