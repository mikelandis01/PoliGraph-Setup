#!/usr/bin/env python3
import csv
import random
import re

import inflect
import spacy
import tqdm
import yaml
from requests_cache import CachedSession
from unidecode import unidecode


def load_list(fname):
    with open(fname) as fin:
        for line in fin:
            line = line.strip()
            if line and not line.startswith('#'):
                yield line


class NERDataGenerator:
    def __init__(self, template_file, data_type_file, actor_entity_list_file):
        self.inflect_engine = inflect.engine()
        
        self.templates = list(load_list(template_file))

        with open(data_type_file) as fin:
            yml_data = yaml.safe_load(fin)

        self.term_aliases = yml_data.pop("alias")
        self.data_types = []
        for v in yml_data.values():
            self.data_types.extend(v)

        self.actor_entities = list(load_list(actor_entity_list_file))

    def __iter__(self):
        return self

    def __next__(self):

        def expand_data_type(term):
            parts = []

            for token in term.split():
                if token[0] == '(' and token[-1] == ')':
                    if random.randint(0, 1) == 0:
                        continue
                    else:
                        token = token[1:-1]

                if token in self.term_aliases:
                    token = random.choice(self.term_aliases[token])

                parts.append(token)

            return " ".join(parts)

        labels = []
        sentence = random.choice(self.templates)

        while True:
            match = re.search('{(?:[A-Z_]+)}', sentence)

            if not match:
                break

            if match[0] == '{DATA}':
                label = "DATA"
                replaced_term = random.choice(self.data_types)
                replaced_term = expand_data_type(replaced_term)

                if random.randint(0, 1) == 0:
                    replaced_term = self.inflect_engine.plural(replaced_term)
            elif match[0] == '{ACTOR}':
                label = "ACTOR"
                replaced_term = random.choice(self.actor_entities)
            else:
                raise ValueError("Invalid template: " + sentence)

            ent_start = match.span()[0]
            labels.append((ent_start, ent_start + len(replaced_term), label))

            if ent_start == 0 and random.randint(0, 1) == 0:
                replaced_term = replaced_term[0].upper() + replaced_term[1:]

            sentence = sentence.replace(match[0], replaced_term, 1)

        return sentence, labels


def main():
    TRAIN_SIZE = 40000
    DEV_SIZE = 10000
    NOISE_RATIO = 0.1
    NOISE_SOURCES = [
        "https://www.gutenberg.org/files/84/84-0.txt",
        "https://www.gutenberg.org/cache/epub/67503/pg67503.txt",
    ]

    spacy.prefer_gpu()

    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")

    session = CachedSession("py_request_cache", backend="filesystem", use_temp=True)
    noise_data = []

    for url in NOISE_SOURCES:
        res = session.get(url)
        for paragraph in re.split(r'(?:\r\n){2,}', res.text):
            paragraph = " ".join(paragraph.split('\r\n'))
            noise_data.extend(unidecode(s.text) for s in nlp(paragraph).sents)

    random.shuffle(noise_data)

    generator = NERDataGenerator("template.txt", "data_types.yml", "actor_entities.list")
    nlp = spacy.blank("en")
    doc_bin = spacy.tokens.DocBin(attrs=["ENT_IOB", "ENT_TYPE"])

    for dataset, size in [("train", TRAIN_SIZE), ("dev", DEV_SIZE)]:
        n_normal_samples = size - int(size * NOISE_RATIO)

        for (text, annotations), i in zip(generator, tqdm.tqdm(range(size))):
            if i <= n_normal_samples:
                doc = nlp(text)
                ents = []
                for start, end, label in annotations:
                    if label in ["DATA", "ACTOR"]:
                        span = doc.char_span(start, end, label=label)
                        ents.append(span)

                doc.ents = ents
            else:
                doc = nlp(noise_data.pop())
                doc.ents = []

            doc_bin.add(doc)

        doc_bin.to_disk(f"{dataset}_dataset.spacy")


if __name__ == "__main__":
    main()
