# ICD-10 Learning Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100.0+-green.svg)](https://fastapi.tiangolo.com/)

An advanced, AI-driven learning agent and API for clinical procedure coding using ICD-10-CM and ICD-10-PCS. The agent leverages LangChain, LangGraph, and DeepAgents to perform reasoning, code retrieval, and provide educational corrections with continuous learning capabilities.

## 🌟 Features

### Core Functionality
- **Automated ICD-10 Coding**: Submit clinical discharge summaries to receive ICD-10-CM diagnosis codes and ICD-10-PCS procedure codes with step-by-step reasoning
- **Real-time Streaming**: Stream the agent's "thinking" process and intermediate steps in real-time via Server-Sent Events
- **Batch Processing**: Process multiple clinical summaries concurrently for high-throughput coding workflows
- **Multi-Modal Retrieval**: Advanced RAG (Retrieval-Augmented Generation) system with vector embeddings and BM25 keyword search across ICD-10 guidelines, diagnosis codes, and procedure codes

### Learning & Corrections
- **Continuous Learning Dashboard**: A web-based interface where users can submit corrections, which the agent stores and learns from to avoid future mistakes
- **Facility-Specific Policies**: Learns from local coding patterns, payer rules, and human corrections
- **Correction Export**: Export collected lessons/corrections to CSV for analysis and compliance reporting

### Technical Features
- **Modular Skill System**: Specialized skills for clinical extraction, diagnosis coding, procedure coding, and validation
- **Medical NLP**: Integrated MedSpacy for clinical entity extraction and negation detection
- **Persistent Memory**: SQLite-based checkpointer and store for conversation persistence and agent memory
- **RESTful API**: FastAPI backend with automatic OpenAPI documentation
- **Modern Frontend**: Vue.js 3 single-page application with real-time updates
- **Docker Deployment**: Containerized deployment with Ollama integration for local LLM inference

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Vue.js SPA    │    │   FastAPI API   │    │   LangGraph     │
│                 │    │                 │    │   Agent         │
│ • Real-time UI  │◄──►│ • REST Endpoints│◄──►│ • Reasoning     │
│ • Chat Interface│    │ • SSE Streaming │    │ • Tool Calling  │
│ • Correction UI │    │ • CORS Enabled  │    │ • Skills        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │   ChromaDB      │    │   SQLite DB     │
                       │   Vector Store  │    │                 │
                       │ • ICD-10 Data   │    │ • Sessions      │
                       │ • Embeddings    │    │ • Corrections   │
                       │ • BM25 Search   │    │ • Checkpoints   │
                       └─────────────────┘    └─────────────────┘
```

## 📋 Prerequisites

- **Python**: 3.9 or higher
- **Node.js**: 16+ (for development, optional for deployment)
- **Docker**: For containerized deployment (optional)
- **Ollama**: For local LLM inference (recommended)

## 🚀 Quick Start

### 1. Clone and Setup

```bash
git clone <your-repo-url>
cd icdagent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration

Create a `.env` file in the project root:

```bash
# LLM Configuration (Ollama recommended for local deployment)
LLM_PROVIDER_STRING=ollama:gemma4:31b
OLLAMA_HOST=http://localhost:11434

# Optional: OpenAI fallback
# OPENAI_API_KEY=your_openai_key
# LLM_PROVIDER_STRING=openai:gpt-4

# RAG Configuration
RAG_EMBEDDING_MODEL_PATH=models/bio_bert

# Database Paths (optional - defaults provided)
AGENT_CHECKPOINT_DB_PATH=runtime/db/agent_checkpoints.sqlite3
AGENT_STORE_DB_PATH=runtime/db/agent_store.sqlite3

# LLM Settings
LLM_TIMEOUT=120
LLM_MAX_RETRIES=3
```

### 3. Download Required Data and Models

The project requires ICD-10 data files and BioBERT embeddings. These are not included in the repository due to size constraints.

#### ICD-10 Data Files
Place the following files in the `data/` directory:
- `diagnoses/icd10cm_codes_2026.txt`
- `diagnoses/icd10cm_tabular_2026.xml`
- `diagnoses/icd10cm_index_2026.xml`
- `diagnoses/icd10cm_eindex_2026.xml`
- `diagnoses/icd10cm_neoplasm_2026.xml`
- `diagnoses/icd10cm_order_2026.txt`
- `diagnoses/icd10cm_drug_2026.xml`
- `procedures/icd10pcs_codes_2026.txt`
- `procedures/icd10pcs_order_2026.txt`
- `guidelines/scenario_cases_01.txt`
- `guidelines/scenario_cases_02.txt`

#### BioBERT Model
Download and place the BioBERT model in `models/bio_bert/`:
```bash
# The model should contain files like:
# config.json, pytorch_model.bin, vocab.txt, etc.
```

### 4. Build RAG Database

```bash
python rag_builder.py
```

This will process the ICD-10 data files and create vector embeddings for efficient retrieval.

### 5. Start Ollama (for Local LLM)

```bash
# Install Ollama from https://ollama.ai
ollama serve

# Pull the required model
ollama pull gemma4:31b
```

### 6. Run the Application

```bash
# Start the FastAPI server
uvicorn app:app --host 0.0.0.0 --port 8000

# Open browser to http://localhost:8000
```

## 🐳 Docker Deployment

For production deployment with Docker:

```bash
# Build and run with Docker Compose
docker-compose up --build

# Or build manually
docker build -t icdagent .
docker run -p 8000:8000 --env-file .env icdagent
```

The Docker setup includes:
- **Ollama service**: Local LLM inference
- **Agent service**: FastAPI application with volume mounts for data persistence

## 📖 API Usage

### Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/code` | POST | Single coding request |
| `/code/stream` | POST | Streaming coding with real-time thoughts |
| `/batch` | POST | Batch processing multiple summaries |
| `/correct` | POST | Submit corrections for learning |
| `/lessons` | GET | View learned corrections |
| `/threads` | GET/POST | Manage conversation threads |
| `/health` | GET | Health check |

### Example API Call

```python
import requests

response = requests.post("http://localhost:8000/code", json={
    "discharge_summary": "Patient admitted with pneumonia, treated with antibiotics..."
})

print(response.json())
# {
#   "result": "ICD-10-CM Diagnoses:\n- J18.9: Pneumonia, unspecified organism\n\nICD-10-PCS Procedures:\n- None\n\nNotes: None\nConfidence: 95",
#   "valid": true,
#   "thread_id": "session_123",
#   "timestamp": "2024-01-01T12:00:00",
#   "reasoning": [...],
#   "icd_codes": [],
#   "pcs_codes": []
# }
```

### Streaming Example

```javascript
const eventSource = new EventSource('/code/stream');
eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'thinking') {
        console.log('Agent thinking:', data.thought);
    } else if (data.type === 'result') {
        console.log('Final result:', data.result);
    }
};
```

## 🎯 Skills System

The agent uses a modular skill system for specialized coding tasks:

- **icd10-clinical-extraction**: Extracts clinical facts from documentation
- **icd10-cm-diagnosis**: Assigns ICD-10-CM diagnosis codes
- **icd10-pcs-procedure**: Assigns ICD-10-PCS procedure codes
- **icd10-validation**: Validates coding accuracy and compliance

Skills are automatically loaded based on the coding task requirements.

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER_STRING` | `ollama:gemma4:31b` | LLM model specification |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `RAG_EMBEDDING_MODEL_PATH` | `models/bio_bert` | Path to embedding model |
| `LLM_TIMEOUT` | `120` | LLM request timeout (seconds) |
| `LLM_MAX_RETRIES` | `3` | Maximum LLM retry attempts |

### Data Directories

- `data/diagnoses/`: ICD-10-CM code files
- `data/procedures/`: ICD-10-PCS code files
- `data/guidelines/`: Coding guidelines and scenarios
- `models/`: Embedding models and tokenizers
- `runtime/db/`: SQLite databases for persistence
- `runtime/chroma/`: Vector database stores

## 🧪 Testing

```bash
# Run the test suite
python -m pytest

# Test specific components
python test_agent.py
python rag_test.py
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

### Development Setup

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run with auto-reload
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## 📊 Monitoring & Logging

- **Health Checks**: `/health` endpoint for service monitoring
- **Thread Management**: Persistent conversation threads with metadata
- **Correction Tracking**: Dashboard for monitoring agent learning progress
- **Export Capabilities**: CSV export of corrections for compliance reporting

## 🔒 Security Considerations

- The application is designed for local deployment
- API endpoints include CORS configuration for web access
- No authentication implemented (add as needed for production)
- Sensitive medical data handling - ensure HIPAA compliance

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **ICD-10 Data**: Official ICD-10-CM and ICD-10-PCS code sets
- **MedSpacy**: Clinical NLP processing
- **LangChain/LangGraph**: Agent framework
- **ChromaDB**: Vector database for RAG
- **Ollama**: Local LLM inference
- **FastAPI**: Modern Python web framework

## 📞 Support

For questions, issues, or contributions:
- Open an issue on GitHub
- Check the API documentation at `/docs`
- Review the skills documentation in `skills/`

---

**Note**: This tool is designed to assist with medical coding but should not replace professional medical coding expertise. Always verify codes with official guidelines and consult with qualified coding professionals.
