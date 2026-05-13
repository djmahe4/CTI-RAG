from abc import ABC, abstractmethod
from typing import List
import math
import jieba
import Stemmer  # PyStemmer Library for English-language dry extraction
import re  # For pre-processing of English text
import json  # To save and load JSON formats
import pickle  # For saving and loading Pickle formats
from .stopwords import (
    STOPWORDS_EN_PLUS,
    STOPWORDS_CHINESE,
)

# Abstract Base Category
class AbstractBM25(ABC):
    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75, stopwords: tuple = ()):
        """
        Abstract Base Category，DefinitionsBM25Core functions
        
        Args:
            corpus: Document set，Each element is a document string
            k1: Parameters to control word saturation
            b: Parameters to control the consolidation of document lengths
            stopwords: Disable Phrase Group
        Raises:
            ValueError: IfcorpusEmpty
        """
        if not corpus:
            raise ValueError("Corpus cannot be empty")
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.stopwords = set(stopwords)  # Convert to set to improve search efficiency
        self.doc_count = len(corpus)

        # Document collection after word-splitting, by subcategory
        self.tokenized_corpus = self._tokenize_corpus()

        # Calculate the length of each document (number of words)
        self.doc_lengths = [len(tokens) for tokens in self.tokenized_corpus]

        # Calculating Average Document Length
        self.avg_doc_length = sum(self.doc_lengths) / self.doc_count if self.doc_count > 0 else 0

        # Word frequency and document frequency
        self.df = {}  # Document Frequency
        self.tf = []  # Word frequency matrix
        self._build_index()

    @abstractmethod
    def _tokenize(self, text: str) -> List[str]:
        """Abstract Method：Split Text"""
        pass

    def _tokenize_corpus(self) -> List[List[str]]:
        """Interpret the whole document collection"""
        return [self._tokenize(doc) for doc in self.corpus]

    def _build_index(self):
        """Build word frequency and document frequency index"""
        for doc_id, tokens in enumerate(self.tokenized_corpus):
            term_freq = {}
            for term in tokens:
                term_freq[term] = term_freq.get(term, 0) + 1
            self.tf.append(term_freq)
            for term in set(tokens):
                self.df[term] = self.df.get(term, 0) + 1

    def _score(self, query_tokens: List[str], doc_id: int) -> float:
        """
        Calculating Query and DocumentBM25Score
        """
        score = 0.0
        doc_len = self.doc_lengths[doc_id]

        for term in query_tokens:
            if term not in self.df:
                continue

            idf = math.log((self.doc_count - self.df[term] + 0.5) /
                          (self.df[term] + 0.5) + 1.0)

            term_freq = self.tf[doc_id].get(term, 0)
            tf_part = term_freq * (self.k1 + 1) / \
                     (term_freq + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_length))

            score += idf * tf_part

        return score

    def search(self, query: str, top_k: int = 5) -> List[tuple]:
        """
        Run search and return sorted results
        """
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        query_tokens = self._tokenize(query)
        scores = [(doc_id, self._score(query_tokens, doc_id))
                 for doc_id in range(self.doc_count)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def save(self, filepath: str):
        """
        WillBM25Index to File（Support JSON and Pickle Format）
        
        Args:
            filepath: Path to saving files（.json or .pkl）
        Raises:
            ValueError: If file extensions are not supported
        """
        data = {
            'df': self.df,
            'tf': self.tf,
            'k1': self.k1,
            'b': self.b,
            'language': 'english' if isinstance(self, EnglishBM25) else 'chinese',
            'stopwords': list(self.stopwords)
        }
        if filepath.endswith('.json'):
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        elif filepath.endswith('.pkl'):
            with open(filepath, 'wb') as f:
                pickle.dump(data, f)
        else:
            raise ValueError("Unsupported file extension. Use .json or .pkl.")

    @classmethod
    def load(cls, filepath: str, corpus: List[str]):
        """
        Load from FileBM25Index（Support JSON and Pickle Format）
        
        Args:
            filepath: Path to index file（.json or .pkl）
            corpus: Original Document Pool，For initialization
        Returns:
            EnglishBM25 or ChineseBM25 Examples
        Raises:
            ValueError: If file extension or language is not supported
        """
        if filepath.endswith('.json'):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        elif filepath.endswith('.pkl'):
            with open(filepath, 'rb') as f:
                data = pickle.load(f)
        else:
            raise ValueError("Unsupported file extension. Use .json or .pkl.")

        language = data['language']
        if language == 'english':
            bm25_cls = EnglishBM25
        elif language == 'chinese':
            bm25_cls = ChineseBM25
        else:
            raise ValueError("Unsupported language in saved data.")

        stopwords = tuple(data['stopwords'])
        bm25 = bm25_cls(corpus, data['k1'], data['b'], stopwords)
        bm25.df = data['df']
        bm25.tf = data['tf']
        bm25.doc_lengths = [sum(tf_doc.values()) for tf_doc in bm25.tf]
        bm25.avg_doc_length = sum(bm25.doc_lengths) / len(bm25.doc_lengths) if bm25.doc_lengths else 0
        return bm25

# BM25 achieved in English (using PyStemmer and disablement)
class EnglishBM25(AbstractBM25):
    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75, stopwords: tuple = STOPWORDS_EN_PLUS):
        """
        EnglishBM25Achieved，UsePyStemmerPerform word dry extraction and disable word filtering
        """
        self.stemmer = Stemmer.Stemmer('english')  # Initialization of English-language dry extractor
        super().__init__(corpus, k1, b, stopwords)

    def _tokenize(self, text: str) -> List[str]:
        """English crosswords：Preprocess with regular expression + PyStemmer + Disable word filtering"""
        text = text.lower()
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', '', text)
        tokens = text.split()
        return [self.stemmer.stemWord(token) for token in tokens if token and token not in self.stopwords]

# BM25 Achieved in Chinese
class ChineseBM25(AbstractBM25):
    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75, stopwords: tuple = STOPWORDS_CHINESE):
        """
        ChineseBM25Achieved，UsejiebaSpelling and Disable Word Filtering
        """
        super().__init__(corpus, k1, b, stopwords)

    def _tokenize(self, text: str) -> List[str]:
        """Chinese：Usejiebaand filter disabled words"""
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z]', '', text)
        tokens = jieba.cut(text)
        return [token for token in tokens if token and token not in self.stopwords]

# Plant Functions
def create_bm25(corpus: List[str],
                language: str, 
                k1: float = 1.5,
                b: float = 0.75,
                stopwords: tuple = None):
    """
    CreateBM25Plant function for instance
    
    Args:
        corpus: Document set
        language: Language type ('english' or 'chinese')
        k1: Parameters to control word saturation
        b: Parameters to control the consolidation of document lengths
        stopwords: Custom Disable Phrases（Optional）
    """
    language = language.lower()
    if language in ['english', 'en']:
        stopwords = stopwords if stopwords is not None else STOPWORDS_EN_PLUS
        return EnglishBM25(corpus, k1, b, stopwords)
    elif language in ['chinese', 'cn']:
        stopwords = stopwords if stopwords is not None else STOPWORDS_CHINESE
        return ChineseBM25(corpus, k1, b, stopwords)
    else:
        raise ValueError("Unsupported language. Please choose 'english/en' or 'chinese/cn'.")
    
def load_bm25(filepath: str, corpus: List[str]):
    """
    Load from FileBM25Examples
    
    Args:
        filepath: Path to index file（.json or .pkl）
        corpus: Original Document Pool，For initialization
    Returns:
        BM25Examples
    """
    return AbstractBM25.load(filepath, corpus)

# Common Search Functions
def bm25_search(corpus: List[str], query: str, language: str, top_k: int = 5, k1: float = 1.5, b: float = 0.75, stopwords: tuple = None):
    """
    ImplementationBM25Search
    """
    bm25 = create_bm25(corpus, language, k1, b, stopwords)
    results = bm25.search(query, top_k)
    return [(doc_id, score, corpus[doc_id]) for doc_id, score in results]
