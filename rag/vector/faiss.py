from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, JSONLoader, TextLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate

# Local embedding model recommended
from langchain_community.embeddings import HuggingFaceEmbeddings
import os
import time
import threading
from typing import List, Tuple, Set
from rag.vector.vector_database import VectorDatabase
import json
from langchain_core.documents import Document

class FaissVectorDatabase(VectorDatabase):
    def __init__(self, path: str = "../data/faiss_index"):
        super().__init__(path)
        
        # Setup paths
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.abspath(os.path.join(base_dir, "../data"))
        self.file_uploads_dir = os.path.join(self.data_dir, "file_uploads")
        self.file_chunks_dir = os.path.join(self.data_dir, "file_chunks")
        self.index_path = os.path.join(self.data_dir, "faiss_index")
        self.exist_file_path = os.path.join(self.data_dir, "file_exist.json")
        
        # Ensure directories exist
        os.makedirs(self.file_uploads_dir, exist_ok=True)
        os.makedirs(self.file_chunks_dir, exist_ok=True)
        os.makedirs(self.index_path, exist_ok=True)
        
        # Initialize model
        model_path = os.path.abspath(os.path.join(base_dir, "../../models/embedding_model/bge-m3"))
        print(f"Attempting to load embedding model: {model_path}")
        
        # Test embedding model
        try:
            self.embeddings = HuggingFaceEmbeddings(
                model_name=model_path
            )
            
            # Test embedding generation
            test_text = "This is a test text to verify if the embedding model is working properly."
            test_embedding = self.embeddings.embed_query(test_text)
            print(f"Embedding model loaded successfully. Generated vector length: {len(test_embedding)}")
        except Exception as e:
            print(f"Failed to load local embedding model: {str(e)}")
            print("Attempting to use online model...")
            try:
                self.embeddings = HuggingFaceEmbeddings(
                    model_name="BAAI/bge-m3"
                )
                test_embedding = self.embeddings.embed_query(test_text)
                print(f"Online embedding model verified successfully.")
            except Exception as e:
                print(f"Online embedding model also failed: {str(e)}")
                raise ValueError("Unable to initialize embedding model. Please check network connectivity and model installation.")
        
        # Create or load vector store
        self.vector_store = self.load_or_create_vector_store(self.index_path)
        
        # Start background auto-update thread
        self.stop_update_thread = False
        self.update_thread = threading.Thread(target=self._auto_update_vector_store)
        self.update_thread.daemon = True
        self.update_thread.start()
        print("Auto-update thread started. Checking for new documents every minute.")

    def query_vector_database(self, query: str) -> List[Document]:
        """Query vector database.
           Uses similarity search to retrieve document snippets.
           Default embedding model: bge-m3
        Args:
            query: Query text string
        Returns:
            docs: List of Document objects
        """
        return self.vector_store.similarity_search(query)

    # Background update thread function
    def _auto_update_vector_store(self):
        """Automatically checks and updates the vector database every minute."""
        while not self.stop_update_thread:
            try:
                print("Checking for new documents...")
                new_files, deleted_files = self.check_file_changes()
                if new_files or deleted_files:
                    print(f"File changes detected. New: {len(new_files)}, Deleted: {len(deleted_files)}")
                    if new_files:
                        self.process_and_update_documents(new_files)
                    # TODO: Handle vector data for deleted files
                # Wait 60s
                time.sleep(60)
            except Exception as e:
                print(f"Error during auto-update: {str(e)}")
                # Retry after 10 seconds on error
                time.sleep(10)
    
    # Stop update thread method
    def stop_auto_update(self):
        """Stop the background auto-update thread."""
        self.stop_update_thread = True
        if self.update_thread.is_alive():
            self.update_thread.join(timeout=2)
            print("Auto-update thread stopped.")

    # 1. Scan local documents
    def load_documents(self):
        """Scans the local upload directory.
        
        Returns: Array of filenames
        """
        # Verify directory exists and is not empty
        if not os.path.exists(self.file_uploads_dir) or not os.listdir(self.file_uploads_dir):
            print(f"Directory {self.file_uploads_dir} does not exist or is empty.")
            return []
        
        file_list = []
        for file in os.listdir(self.file_uploads_dir):
            file_path = os.path.join(self.file_uploads_dir, file)
            if os.path.isfile(file_path):
                file_list.append(file)
        
        print(f"Loaded {len(file_list)} documents.")
        return file_list

    # Helper function: check FAISS index existence
    def faiss_index_exists(self, index_path: str = "../data/faiss_index") -> bool:
        """Check if FAISS index files exist locally."""
        required_files = ["index.faiss", "index.pkl"]
        return all(os.path.exists(os.path.join(index_path, f)) for f in required_files)
    
    # Check for file changes
    def check_file_changes(self) -> Tuple[List[str], List[str]]:
        """Check for file changes and return lists of new and deleted files."""
        # Get current file list
        current_files = set(self.load_documents())
        
        # Read existing file list registry
        exist_files = set()
        if os.path.exists(self.exist_file_path):
            try:
                with open(self.exist_file_path, 'r', encoding='utf-8') as f:
                    exist_files = set(json.load(f))
            except Exception as e:
                print(f"Error reading existing file list: {str(e)}")
        
        # Calculate diff
        new_files = list(current_files - exist_files)
        deleted_files = list(exist_files - current_files)
        
        # Update registry
        if new_files or deleted_files:
            updated_exist_files = list(current_files)
            with open(self.exist_file_path, 'w', encoding='utf-8') as f:
                json.dump(updated_exist_files, f, ensure_ascii=False)
            print(f"Updated file registry: Total {len(updated_exist_files)} files.")
        
        return new_files, deleted_files
    
    # Process documents
    def process_documents(self, file_list: List[str], data_path: str) -> Tuple[List, List]:
        """Loads documents from folder, splits text, and returns processed metadata.
        
        Args:
            file_list: List of files to process
            data_path: Directory path containing files
        Returns:
            processed_files: List of successfully processed filenames
            split_docs: List of Document chunks
        """
        
        documents = []
        processed_files = []
        # Traverse data_path and process files matching file_list
        supported_extensions = [".pdf", ".json", ".txt", ".docx"]
        for root, _, files in os.walk(data_path):
            for file in files:
                file_ext = os.path.splitext(file)[1].lower()
                
                # Verify file is in the target list and has a supported extension
                if file in file_list and file_ext in supported_extensions:
                    try:
                        file_path = os.path.join(root, file)
                        # Select appropriate loader based on file extension
                        if file_ext == ".pdf":
                            loader = PyPDFLoader(file_path)
                        elif file_ext == ".json":
                            loader = JSONLoader(file_path, encoding="utf-8")
                        elif file_ext == ".txt":
                            loader = TextLoader(file_path, encoding="utf-8")
                        elif file_ext == ".docx":
                            loader = Docx2txtLoader(file_path)
                            
                        # Load document
                        doc = loader.load()
                        documents.extend(doc)
                        processed_files.append(file)
                        print(f"Loaded file: {file}")
                    except Exception as e:
                        print(f"Error loading file {file}: {str(e)}")
        
        if not documents:
            print("No valid documents found.")
            return processed_files, []

        # Split text into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=3000,           # Max characters per chunk
            chunk_overlap=1000,        # Overlap between adjacent chunks
            length_function=len,       # Function to calculate text length
            is_separator_regex=False,  # If True, treat separator as regex
        )
        split_docs = text_splitter.split_documents(documents)
        
        return processed_files, split_docs
    
    # Save split chunks
    def save_split_docs(self, split_docs: List, chunk_path: str):
        """Saves document chunks to local text files."""
        os.makedirs(chunk_path, exist_ok=True)
        for i, doc in enumerate(split_docs):
            base_filename = os.path.splitext(os.path.basename(doc.metadata["source"]))[0]
            chunk_filename = f"{chunk_path}/{base_filename}_chunk_{i}.txt"
            with open(chunk_filename, "w", encoding="utf-8") as f:
                f.write(doc.page_content)
            
        print(f"Saved {len(split_docs)} document chunks.")
    
    # Unified process and update function
    def process_and_update_documents(self, file_list: List[str]):
        """Processes new documents, saves chunks, and updates the vector database."""
        
        # Process docs
        processed_files, new_split_docs = self.process_documents(file_list, self.file_uploads_dir)
        print(f"Processed files: {processed_files}")
        
        # Save chunks and update store
        if new_split_docs:
            self.save_split_docs(new_split_docs, self.file_chunks_dir)
            
            # Update vector database
            print(f"Adding {len(new_split_docs)} new document chunks to vector database...")
            self.vector_store.add_documents(new_split_docs)
            self.vector_store.save_local(self.index_path)
            print("Vector database update complete!")
        else:
            print("No valid documents processed; no update required.")
        
        return new_split_docs

    # Create or load vector store
    def load_or_create_vector_store(self, index_path: str = "../data/faiss_index"):
        """Intelligently creates or loads the vector database."""

        if self.faiss_index_exists(index_path):
            print("Existing vector database detected. Loading...")
            return FAISS.load_local(
                folder_path=index_path,
                embeddings=self.embeddings,
                allow_dangerous_deserialization=True
            )
        else:
            print("Creating new vector database...")
            # Load initial documents
            file_list = self.load_documents()
            
            # Check for empty file list
            if not file_list:
                print("Warning: No documents found! Ensure the directory contains PDF, TXT, JSON, or DOCX files.")
                # Create an empty initial vector store
                vector_store = FAISS.from_documents(
                    documents=[Document(page_content="Initialization", metadata={"source": "faiss_initialization"})],
                    embedding=self.embeddings
                )
                vector_store.save_local(index_path)
                return vector_store
                            
            # Process documents
            processed_files, split_docs = self.process_documents(file_list, self.file_uploads_dir)
            
            # Save chunks
            self.save_split_docs(split_docs, self.file_chunks_dir)
            
            # Update file registry
            with open(self.exist_file_path, 'w', encoding='utf-8') as f:
                json.dump(processed_files, f, ensure_ascii=False)
            print(f"Initialized file registry with {len(processed_files)} files.")

            print(f"Creating vector database with {len(split_docs)} chunks...")           
            # Create vector store from documents
            vector_store = FAISS.from_documents(
                documents=split_docs,
                embedding=self.embeddings
            )
            vector_store.save_local(index_path)
            return vector_store

    # Update vector database
    def update_vector_store(self, file_list: List[str]):
        """Dynamically update existing vector database."""
        return self.process_and_update_documents(file_list)
