import pandas as pd
import glob
import os
import xml.etree.ElementTree as ET
import sqlite3
import pickle
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document
from dotenv import load_dotenv
from project_paths import BASE_DIR, CHROMA_DIR, DB_DIR, ensure_runtime_dirs

load_dotenv()
ensure_runtime_dirs()

PERSIST_DIR_BASE = str(CHROMA_DIR)
DB_PATH = str(DB_DIR / "processed_files.sqlite3")

# We define the three collections
COLLECTIONS = {
    "diagnoses": {
        "dir": "data/diagnoses",
        "persist_dir": os.path.join(PERSIST_DIR_BASE, "diagnoses_store"),
        "name": "diagnoses_2026",
        "bm25_path": os.path.join(PERSIST_DIR_BASE, "diagnoses_bm25.pkl")
    },
    "procedures": {
        "dir": "data/procedures",
        "persist_dir": os.path.join(PERSIST_DIR_BASE, "procedures_store"),
        "name": "procedures_2026",
        "bm25_path": os.path.join(PERSIST_DIR_BASE, "procedures_bm25.pkl")
    },
    "guidelines": {
        "dir": "data/guidelines",
        "persist_dir": os.path.join(PERSIST_DIR_BASE, "guidelines_store"),
        "name": "guidelines_2026",
        "bm25_path": os.path.join(PERSIST_DIR_BASE, "guidelines_bm25.pkl")
    }
}

_LOCAL_BIOBERT_MODEL_PATH = os.getenv(
    "RAG_EMBEDDING_MODEL_PATH",
    str(BASE_DIR / "models" / "bio_bert"),
)

def get_embedding_function():
    return HuggingFaceEmbeddings(
        model_name=_LOCAL_BIOBERT_MODEL_PATH,
        model_kwargs={"device": "cpu", "local_files_only": True},
        encode_kwargs={"normalize_embeddings": True}
    )

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_files (
            file_path TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            last_modified REAL NOT NULL,
            num_entries INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def _extract_codes(file_path):
    extracted = []
    filename = file_path.lower()
    
    # We only want the clean TXT files like icd10cm_codes_2026.txt and icd10pcs_codes_2026.txt
    if 'codes' not in filename or not filename.endswith('.txt'):
        return extracted
        
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # Split on the first occurrence of multiple spaces or tabs
                parts = line.split(None, 1)
                if len(parts) == 2:
                    code = parts[0].strip()
                    desc = parts[1].strip()
                    
                    # Ensure it looks like a valid code (e.g. A000 or 0016070)
                    if 3 <= len(code) <= 7 and len(desc) > 3:
                        # Insert dot for CM codes if longer than 3 characters (e.g. A000 -> A00.0)
                        if 'cm' in filename and len(code) > 3:
                            code = f"{code[:3]}.{code[3:]}"
                        
                        extracted.append(f"{code} | {desc}")
    except Exception as e:
        print(f"      ⚠️ Skipped codes in {os.path.basename(file_path)} ({e})")
    return extracted

def _extract_guidelines(file_path):
    extracted = []
    filename = file_path.lower()
    try:
        if filename.endswith('.pdf'):
            loader = PyPDFLoader(file_path)
            docs = loader.load()
        elif filename.endswith('.txt'):
            loader = TextLoader(file_path, encoding='utf-8')
            docs = loader.load()
        else:
            return []
        
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=2500, chunk_overlap=500, separators=["\n\n", "\n", ".", " "])
        splits = text_splitter.split_documents(docs)
        for doc in splits:
            extracted.append(doc.page_content)
    except Exception as e:
        print(f"      ⚠️ Skipped guidelines in {os.path.basename(file_path)} ({e})")
    return extracted

class CustomBM25Retriever:
    """Wrapper to make BM25 compatible with Langchain's EnsembleRetriever (Simplified)"""
    def __init__(self, docs):
        self.docs = docs
        self.corpus = [doc.page_content.lower().split() for doc in docs]
        self.bm25 = BM25Okapi(self.corpus)
        
    def invoke(self, query: str, **kwargs):
        tokenized_query = query.lower().split()
        top_n = kwargs.get('k', 4)
        scores = self.bm25.get_scores(tokenized_query)
        # Get top N indices
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_n]
        return [self.docs[i] for i in top_indices if scores[i] > 0]
        
    async def ainvoke(self, query: str, **kwargs):
        return self.invoke(query, **kwargs)

def build_collection(coll_key, coll_info, processed, cursor, embeddings):
    print(f"\n🔍 Processing {coll_key.upper()} collection...")
    
    files = glob.glob(f"{coll_info['dir']}/**/*", recursive=True)
    files = [f for f in files if f.lower().endswith(('.csv', '.txt', '.xml', '.pdf')) and os.path.isfile(f)]
    
    if not files:
        print(f"   ❌ No files found in {coll_info['dir']}")
        return False

    persist_dir = coll_info['persist_dir']
    collection_name = coll_info['name']
    
    # Load existing Chroma
    vectorstore = None
    if os.path.isdir(persist_dir) and bool(os.listdir(persist_dir)):
        vectorstore = Chroma(
            persist_directory=persist_dir,
            collection_name=collection_name,
            embedding_function=embeddings,
        )
    
    new_texts = []
    new_metadatas = []
    db_updates = []
    
    # Track all documents for BM25 rebuild (if any updates occur)
    # Since BM25 is not easily incremental, we rebuild it if there are any changes in the collection.
    has_changes = False

    for file_path in files:
        abs_path = os.path.abspath(file_path)
        current_mtime = os.path.getmtime(file_path)

        is_new_or_updated = abs_path not in processed or processed[abs_path] < current_mtime

        if is_new_or_updated:
            has_changes = True
            if vectorstore is not None and abs_path in processed:
                print(f"   🔄 Updating {os.path.basename(file_path)} → deleting old embeddings...")
                try:
                    vectorstore.delete(where={"source": abs_path})
                except Exception as e:
                    pass

            if coll_key == "guidelines":
                extracted = _extract_guidelines(file_path)
            else:
                extracted = _extract_codes(file_path)
                
            db_updates.append((abs_path, coll_key, current_mtime, len(extracted)))

            if extracted:
                for text in extracted:
                    new_texts.append(text)
                    new_metadatas.append({"source": abs_path})
                    
    if new_texts:
        print(f"   ✅ Extracted {len(new_texts)} new/updated entries from {len(db_updates)} files.")
        if vectorstore is None:
            # Create an empty vectorstore first
            vectorstore = Chroma(
                persist_directory=persist_dir,
                collection_name=collection_name,
                embedding_function=embeddings
            )
        
        # Add texts in batches of 5000 to show progress
        batch_size = 5000
        total_batches = (len(new_texts) + batch_size - 1) // batch_size
        for i in range(0, len(new_texts), batch_size):
            batch_texts = new_texts[i:i+batch_size]
            batch_metadatas = new_metadatas[i:i+batch_size]
            print(f"      📦 Adding batch {(i//batch_size)+1}/{total_batches} ({len(batch_texts)} entries)...")
            vectorstore.add_texts(texts=batch_texts, metadatas=batch_metadatas)

    if db_updates:
        for abs_path, c_key, mtime, num_entries in db_updates:
            cursor.execute("""
                INSERT OR REPLACE INTO processed_files 
                (file_path, collection, last_modified, num_entries) 
                VALUES (?, ?, ?, ?)
            """, (abs_path, c_key, mtime, num_entries))
            
    # Rebuild BM25 if there were changes and vectorstore exists
    if vectorstore is not None and (has_changes or not os.path.exists(coll_info['bm25_path'])):
        print(f"   📊 Rebuilding BM25 index for {coll_key}...")
        try:
            # Fetch all documents in batches to avoid SQLite "too many variables" limits
            all_texts = []
            all_metadatas = []
            offset = 0
            limit = 5000
            
            while True:
                batch_docs = vectorstore.get(limit=limit, offset=offset)
                b_texts = batch_docs.get('documents', [])
                b_metas = batch_docs.get('metadatas', [])
                
                if not b_texts:
                    break
                    
                all_texts.extend(b_texts)
                all_metadatas.extend(b_metas)
                offset += limit
            
            docs_for_bm25 = [
                Document(page_content=t, metadata=m) for t, m in zip(all_texts, all_metadatas)
            ]
            
            bm25_retriever = CustomBM25Retriever(docs_for_bm25)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(coll_info['bm25_path']), exist_ok=True)
            
            with open(coll_info['bm25_path'], 'wb') as f:
                pickle.dump(bm25_retriever, f)
            print(f"   💾 Saved BM25 index to {coll_info['bm25_path']} with {len(docs_for_bm25)} entries")
        except Exception as e:
            print(f"   ⚠️ Failed to build/save BM25 index: {e}")

    if not has_changes:
        print(f"   ✅ {coll_key} is already up to date!")
        
    return has_changes

def build_rag():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT file_path, last_modified FROM processed_files")
    processed = {row[0]: row[1] for row in cursor.fetchall()}
    embeddings = get_embedding_function()

    any_updates = False
    for coll_key, coll_info in COLLECTIONS.items():
        if os.path.exists(coll_info['dir']):
            changes = build_collection(coll_key, coll_info, processed, cursor, embeddings)
            if changes:
                any_updates = True
        else:
            print(f"⚠️ Directory {coll_info['dir']} does not exist.")

    conn.commit()
    conn.close()

    if any_updates:
        print(f"\n🎉 RAG Multi-Collection build complete!")
    else:
        print(f"\n✅ All RAG collections are up to date.")

if __name__ == "__main__":
    build_rag()
