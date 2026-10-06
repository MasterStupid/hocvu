# HocVu AI

HocVu AI is a Vietnamese, grounded voice assistant for looking up academic regulations. It implements the research proposal's core pipeline: a regulation knowledge base, chunking and retrieval, citation-backed answers with abstention, multi-turn session storage, browser voice input/output, and a repeatable retrieval evaluation.

## Run locally

On Windows, the quickest option is to double-click `run.bat`. It opens the
application in the browser. Local semantic retrieval is enabled by default;
the first run may download the embedding model. Set `HV_SEMANTIC=0` before
starting it when you explicitly want BM25-only retrieval. Keep its terminal
window open while using the project; press `Ctrl+C` there to stop it.

```powershell
python manage.py ingest
python manage.py serve --open
```

Open `http://127.0.0.1:8000`. Use Chrome or Edge for Vietnamese browser speech recognition; text-to-speech uses the browser's Vietnamese voice when available.

## AI-assisted answers and Live conversation

The **AI** switch on the main page is off by default. When enabled, the
system first retrieves grounded excerpts, then asks the configured LLM to make
the answer more natural for speech. Citations still come from the local
retrieval result. If no LLM key is configured or the request fails, HocVu AI
keeps the extractive answer and labels it as a fallback.

To enable the optional OpenAI Responses API integration for the current
PowerShell session, set these variables before starting the server:

```powershell
$env:HV_LLM = "openai"
$env:OPENAI_API_KEY = "your_api_key"
# Optional: $env:OPENAI_MODEL = "your-selected-model"
python manage.py serve
```

When the AI switch is on, the user's question and only the retrieved excerpts
for that turn are sent to the configured LLM provider. Do not enable it for
sensitive documents unless that data transfer is approved.

Select **Live** to start a hands-free dialogue: after the first user click and
microphone permission, the browser listens, sends a turn, reads the response,
then opens the microphone for the next turn. This uses the browser's speech
recognition and speech synthesis; browser vendors may process speech according
to their own privacy settings. Audio is not uploaded to this Python server.

DOCX works with the Python standard library. Install the dependencies before the first run:

```powershell
python -m pip install -r requirements.txt
```

The first index build downloads `intfloat/multilingual-e5-small` for local
Vietnamese semantic retrieval (approximately 500 MB for model weights, in
addition to the AI runtime). The application falls back to keyword search if
the model cannot be downloaded. Set `HV_EMBEDDING_MODEL` to use a different
Sentence Transformers model.

## Add and manage regulations

Open **Quản lý tài liệu** from the top navigation or visit `http://127.0.0.1:8000/documents.html`. Select multiple PDF, DOCX or image files (up to 25 MB each), set the order number, decision number, article/clause and effective date for each file, then upload the queue. The page immediately rebuilds the retrieval index, can show the normalized extracted text and number of indexed chunks, and supports selecting and removing queued or previously uploaded files. Encrypted PDFs are rejected.

Enable **OCR tiếng Việt** for a screenshot/photo, scanned PDF, or DOCX containing scanned images. OCR runs locally with Tesseract: image files are read entirely; PDF OCR runs only on pages without a usable text layer; and DOCX OCR reads images embedded in the file. It works best with clear, upright Vietnamese text. PDFs/DOCX with normal selectable text keep their native extraction.

## Research workflow

```powershell
python manage.py ask "Điều kiện bảo lưu kết quả học tập là gì?"
python manage.py evaluate
```

`evaluate` writes `data/eval_result.json`, reporting citation-grounding accuracy and refusal accuracy. WER, TTS quality, response latency, and user satisfaction must be recorded with real participant data during the pilot, as stated in the proposal.

## Important data note

The bundled corpus is intentionally labelled demonstration data. It is not an official regulation database and must be replaced and reviewed by the university before real-world use. The system is designed to abstain when it lacks enough relevant evidence rather than invent a rule.

## Architecture

```text
Student text or voice
        | (browser STT)
        v
Intent and safety gate -> Vietnamese tokenization -> Hybrid BM25 + AI embedding retrieval
                                                   -> grounded answer + citations
        ^                                                               |
        +------------------------ SQLite session <---------------------+
                                                                        |
                                                            browser TTS v
```
