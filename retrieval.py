import os
import pickle
from langchain_chroma import Chroma
from langchain_classic.retrievers import EnsembleRetriever
from rag_builder import get_embedding_function, COLLECTIONS, CustomBM25Retriever

# Cache to avoid reloading the vector stores and models
_RETRIEVERS_CACHE = {}

def get_hybrid_retriever(collection_type: str):
    """
    Returns an EnsembleRetriever (BM25 + Vector) for the specified collection type.
    collection_type must be one of: 'diagnoses', 'procedures', 'guidelines'.
    """
    global _RETRIEVERS_CACHE

    if collection_type not in COLLECTIONS:
        raise ValueError(f"Invalid collection type: {collection_type}. Must be one of {list(COLLECTIONS.keys())}")

    if collection_type in _RETRIEVERS_CACHE:
        return _RETRIEVERS_CACHE[collection_type]

    coll_info = COLLECTIONS[collection_type]
    
    # 1. Load Chroma Vector Store
    if not os.path.isdir(coll_info['persist_dir']) or not os.listdir(coll_info['persist_dir']):
        print(f"⚠️ Vector store for {collection_type} not found. Run rag_builder.py first.")
        return None

    embeddings = get_embedding_function()
    vectorstore = Chroma(
        persist_directory=coll_info['persist_dir'],
        collection_name=coll_info['name'],
        embedding_function=embeddings,
    )
    # Configure semantic retriever (e.g. top 5)
    semantic_retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

    # 2. Load Pickled BM25 Retriever
    bm25_retriever = None
    if os.path.exists(coll_info['bm25_path']):
        try:
            import __main__
            __main__.CustomBM25Retriever = CustomBM25Retriever
            with open(coll_info['bm25_path'], 'rb') as f:
                bm25_retriever = pickle.load(f)
        except Exception as e:
            print(f"⚠️ Could not load BM25 index for {collection_type}: {e}")

    # 3. Create Ensemble Retriever
    if bm25_retriever is not None:
        # We wrap the custom BM25 retriever slightly if needed, but EnsembleRetriever accepts anything with an invoke method returning documents.
        # Ensure our CustomBM25Retriever is compatible. Langchain's EnsembleRetriever expects BaseRetriever, but duck typing usually works.
        # If it doesn't, we can fallback to standard. Our CustomBM25Retriever implements invoke/ainvoke.
        
        # We need to wrap it into a BaseRetriever to make EnsembleRetriever happy.
        from langchain_core.retrievers import BaseRetriever
        from typing import List
        from langchain_core.callbacks import CallbackManagerForRetrieverRun
        from langchain_core.documents import Document

        class WrappedBM25Retriever(BaseRetriever):
            custom_bm25: CustomBM25Retriever
            
            def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> List[Document]:
                return self.custom_bm25.invoke(query, k=5)

        wrapped_bm25 = WrappedBM25Retriever(custom_bm25=bm25_retriever)

        if collection_type == "diagnoses":
            weights=[0.7, 0.3]  # BM25 stronger for exact codes
        elif collection_type == "procedures":
            weights=[0.6, 0.4]
        else:
            weights=[0.4, 0.6]  # guidelines = semantic heavy

        ensemble_retriever = EnsembleRetriever(
            retrievers=[wrapped_bm25, semantic_retriever],
            weights=weights
        )
        _RETRIEVERS_CACHE[collection_type] = ensemble_retriever
        return ensemble_retriever
    else:
        print(f"⚠️ Falling back to pure semantic search for {collection_type} (BM25 missing).")
        _RETRIEVERS_CACHE[collection_type] = semantic_retriever
        return semantic_retriever
