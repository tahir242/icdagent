# Run this once in a separate script with stable internet:
from huggingface_hub import snapshot_download

# Download all-MiniLM-L6-v2
snapshot_download(
    repo_id="sentence-transformers/all-MiniLM-L6-v2",
    repo_type="model",
    local_dir="D:\\Python-Projects\\icdagent\\models\\embedding_models\\all-MiniLM-L6-v2"
)

# Download BioBERT model
snapshot_download(
    repo_id="pritamdeka/BioBERT-mnli-snli-snli-scitail-mednli-stsb",
    repo_type="model", 
    local_dir="D:\\Python-Projects\\icdagent\\models\\bio_bert"
)