"""
This code converts MS MARCO train, dev and eval tsv data into the tfrecord files
that will be consumed by BERT.
"""
import collections
import os
import re
import tensorflow as tf
import time
# local module
import tokenization


flags = tf.flags

FLAGS = flags.FLAGS


flags.DEFINE_string(
    "output_folder", None,
    "Folder where the tfrecord files will be written.")

flags.DEFINE_string(
    "vocab_file",
    "./data/bert/uncased_L-24_H-1024_A-16/vocab.txt",
    "The vocabulary file that the BERT model was trained on.")

flags.DEFINE_string(
    "train_dataset_path",
    "./data/triples.train.small.tsv",
    "Path to the MSMARCO training dataset containing the tab separated "
    "<query, positive_paragraph, negative_paragraph> tuples.")

flags.DEFINE_string(
    "dev_dataset_path",
    "./data/top1000.dev.tsv",
    "Path to the MSMARCO training dataset containing the tab separated "
    "<query, positive_paragraph, negative_paragraph> tuples.")

flags.DEFINE_string(
    "eval_dataset_path",
    "./data/top1000.eval.tsv",
    "Path to the MSMARCO eval dataset containing the tab separated "
    "<query, positive_paragraph, negative_paragraph> tuples.")

flags.DEFINE_string(
    "dev_qrels_path",
    "./data/qrels.dev.tsv",
    "Path to the query_id relevant doc ids mapping.")

flags.DEFINE_integer(
    "max_seq_length", 512,
    "The maximum total input sequence length after WordPiece tokenization. "
    "Sequences longer than this will be truncated, and sequences shorter "
    "than this will be padded.")

flags.DEFINE_integer(
    "max_query_length", 64,
    "The maximum query sequence length after WordPiece tokenization. "
    "Sequences longer than this will be truncated.")

flags.DEFINE_integer(
    "num_eval_docs", 1000,
    "The maximum number of docs per query for dev and eval sets.")


def write_to_tf_record(writer, tokenizer, query, docs, labels,
                       ids_file=None, query_id=None, doc_ids=None):
  query = tokenization.convert_to_unicode(query) #Assigns a special character to each letter in the query, since Python only reads letters in unicode
  query_token_ids = tokenization.convert_to_bert_input(
      text=query, max_seq_length=FLAGS.max_query_length, tokenizer=tokenizer, 
      add_cls=True) #adds the [CLS] and [SEP] tokens to the sequence and replaces each token with its ID from BERTs vocabularly. Text should be in unicode format

  query_token_ids_tf = tf.train.Feature(
      int64_list=tf.train.Int64List(value=query_token_ids)) #converts the query to a tensor

  for i, (doc_text, label) in enumerate(zip(docs, labels)): #docs and label are lists. Docs consists of a postive and negative document and lists consists of a 1 and 0 

    doc_token_id = tokenization.convert_to_bert_input(
          text=tokenization.convert_to_unicode(doc_text),
          max_seq_length=FLAGS.max_seq_length - len(query_token_ids),
          tokenizer=tokenizer,
          add_cls=False) #converts the document to unicode, then adds the [CLS] and [SEP] tokens and finally replaces each token with its token ID from BERTs vocabularly

    doc_ids_tf = tf.train.Feature(
        int64_list=tf.train.Int64List(value=doc_token_id)) #converts the query to a tensor

    labels_tf = tf.train.Feature(
        int64_list=tf.train.Int64List(value=[label])) #converts the query to a tensor

    features = tf.train.Features(feature={ #Features contains a dictionary that maps each feature name to its feature alue 
        'query_ids': query_token_ids_tf,
        'doc_ids': doc_ids_tf,
        'label': labels_tf, #Each instance in the dataset contains 3 features: query_ids, doc_ids and label 
    })
    example = tf.train.Example(features=features)#an example is a single instance from a dataset. Each example contains a single features
    writer.write(example.SerializeToString()) #SerializeToString converts the dataset instance to a binary format which can be saved and transmitted over a network

    if ids_file:
     ids_file.write('\t'.join([query_id, doc_ids[i]]) + '\n')

def convert_eval_dataset(set_name, tokenizer):
  print('Converting {} set to tfrecord...'.format(set_name))
  start_time = time.time()

  if set_name == 'dev':
    dataset_path = FLAGS.dev_dataset_path #FLAGS allows for a variable to be changed from the runtime environment 
    relevant_pairs = set() #a set is a collection of elements
    with open(FLAGS.dev_qrels_path) as f: #qrels is a file which contrains the ground truth documents for each passage
      for line in f:
        query_id, _, doc_id, _ = line.strip().split('\t') #underscore represents a throw-away variable
        relevant_pairs.add('\t'.join([query_id, doc_id])) #joins query_id and doc_id into a single string with a space between them. The string is then added to the set
  else:
    dataset_path = FLAGS.eval_dataset_path

  #executes the below code for both the development and evaluation sets
  queries_docs = collections.defaultdict(list)  
  query_ids = {} #creates a dictionary. [] = list, () = tuple, {} = dictionary or set
  with open(dataset_path, 'r') as f:
    for i, line in enumerate(f):
      query_id, doc_id, query, doc = line.strip().split('\t') #assigns the result of the split to each variable
      label = 0 #no labels are needed for the evaluation set
      if set_name == 'dev':
        if '\t'.join([query_id, doc_id]) in relevant_pairs:
          label = 1
      queries_docs[query].append((doc_id, doc, label)) #each query will represent a new key in the dictionary. This means that each query is associated with a doc_id, doc and label 
      query_ids[query] = query_id #query_id is assigned to the query key in the query_ids dictionary

  # Add fake paragraphs to the queries that have less than FLAGS.num_eval_docs.
  queries = list(queries_docs.keys())  # Need to copy keys before iterating. This creates a list of all the quries from the dev or eval dataset
  for query in queries:
    docs = queries_docs[query] #assigns the values associated with the query key to docs (doc-id, doc, label)
    docs += max(
        0, FLAGS.num_eval_docs - len(docs)) * [('00000000', 'FAKE DOCUMENT', 0)] #max() returns the item with the highest value. The number of fake documents added to the docs list is determined by subtracting number of documents from the required number of documents 
    queries_docs[query] = docs #sets docs as the new value for the query key

  assert len(
      set(len(docs) == FLAGS.num_eval_docs for docs in queries_docs.values())) == 1, (
          'Not all queries have {} docs'.format(FLAGS.num_eval_docs))

  writer = tf.python_io.TFRecordWriter(
      FLAGS.output_folder + '/dataset_' + set_name + '.tf')

  query_doc_ids_path = (
      FLAGS.output_folder + '/query_doc_ids_' + set_name + '.txt')
  with open(query_doc_ids_path, 'w') as ids_file: #-w writes information to the query_doc_ids_path file
    for i, (query, doc_ids_docs) in enumerate(queries_docs.items()): #.items returns a list of the key and its associated values. query = query and doc_ids_docs = (doc_id, doc, label)
      doc_ids, docs, labels = zip(*doc_ids_docs) #zip(*doc_ids_docs) = doc_id, doc, label
      query_id = query_ids[query]

      write_to_tf_record(writer=writer, #the writer is set to the output file path
                         tokenizer=tokenizer,
                         query=query, 
                         docs=docs, 
                         labels=labels,
                         ids_file=ids_file,
                         query_id=query_id,
                         doc_ids=doc_ids)

      if i % 100 == 0:
        print('Writing {} set, query {} of {}'.format(
            set_name, i, len(queries_docs)))
        time_passed = time.time() - start_time
        hours_remaining = (
            len(queries_docs) - i) * time_passed / (max(1.0, i) * 3600)
        print('Estimated hours remaining to write the {} set: {}'.format(
            set_name, hours_remaining))
  writer.close()


def convert_train_dataset(tokenizer):
  print('Converting to Train to tfrecord...')

  start_time = time.time()

  print('Counting number of examples...')
  num_lines = sum(1 for line in open(FLAGS.train_dataset_path, 'r')) #opens the file for reading
  print('{} examples found.'.format(num_lines)) 
  writer = tf.python_io.TFRecordWriter(
      FLAGS.output_folder + '/dataset_train.tf') #specifies the output file path where the results will be written

  with open(FLAGS.train_dataset_path, 'r') as f:
    for i, line in enumerate(f):
      if i % 1000 == 0:
        time_passed = int(time.time() - start_time)
        print('Processed training set, line {} of {} in {} sec'.format(
            i, num_lines, time_passed))
        hours_remaining = (num_lines - i) * time_passed / (max(1.0, i) * 3600)
        print('Estimated hours remaining to write the training set: {}'.format(
            hours_remaining))

      query, positive_doc, negative_doc = line.rstrip().split('\t') #rstrip() eliminates any white spaces and split('t') splits the line into a list using 't' as a delimiter

      write_to_tf_record(writer=writer, #the writer is set to the output file path
                         tokenizer=tokenizer,
                         query=query, 
                         docs=[positive_doc, negative_doc], 
                         labels=[1, 0])

  writer.close()


def main():

  print('Loading Tokenizer...')
  tokenizer = tokenization.FullTokenizer(
      vocab_file=FLAGS.vocab_file, do_lower_case=True)

  if not os.path.exists(FLAGS.output_folder):
    os.mkdir(FLAGS.output_folder)

  convert_train_dataset(tokenizer=tokenizer)
  convert_eval_dataset(set_name='dev', tokenizer=tokenizer)
  convert_eval_dataset(set_name='eval', tokenizer=tokenizer)
  print('Done!')  

if __name__ == '__main__':
  main()
