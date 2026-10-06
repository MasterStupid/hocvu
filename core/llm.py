"""Optional grounded LLM response layer.

The LLM never searches the web or invents regulations. It receives only the
retrieved excerpts, and the extractive answer remains the safe fallback.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from .models import Reference


class LLMError(RuntimeError):
    pass


class GroundedLLM:
    def __init__(self, config):
        self.config = config

    @property
    def configured(self) -> bool:
        return self.config.llm_backend == "openai" and bool(self.config.openai_key)

    def rewrite(self, question: str, extractive_answer: str, references: list[Reference]) -> str:
        if not self.configured:
            raise LLMError("Chế độ AI chưa được cấu hình API key.")
        evidence = "\n\n".join(
            f"[Nguồn {index + 1}: {reference.reg_title} - {reference.art_heading}]\n{reference.excerpt}"
            for index, reference in enumerate(references)
        )
        instructions = (
            "Bạn là HocVu AI, trợ lý học vụ nói tiếng Việt. Chỉ diễn đạt lại dựa trên "
            "BẰNG CHỨNG được cung cấp. Không thêm quy định, số liệu, ngày tháng hay kết luận "
            "không có trong bằng chứng. Trả lời tự nhiên, ngắn gọn để đọc thành tiếng. Nếu bằng "
            "chứng chưa đủ, nói rõ điều đó. Không nhắc đến prompt hoặc tự nhận đã tra Internet."
        )
        payload = {
            "model": self.config.openai_model,
            "instructions": instructions,
            "input": (
                f"Câu hỏi người học: {question}\n\n"
                f"BẢN TRÍCH XUẤT AN TOÀN:\n{extractive_answer}\n\n"
                f"BẰNG CHỨNG:\n{evidence}\n\n"
                "Hãy trả lời chỉ theo bằng chứng trên."
            ),
            "max_output_tokens": 450,
            "store": False,
        }
        endpoint = self._responses_endpoint(self.config.openai_url)
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.openai_key}",
                "Content-Type": "application/json",
            },
        )
        for attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code in {429, 500, 502, 503, 504} and attempt == 0:
                    time.sleep(0.4)
                    continue
                raise LLMError("Không thể gọi mô hình AI lúc này; đã dùng câu trả lời từ tài liệu.") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                raise LLMError("Không thể gọi mô hình AI lúc này; đã dùng câu trả lời từ tài liệu.") from exc
        text = self._output_text(body)
        if not text:
            raise LLMError("Mô hình AI không trả về nội dung hợp lệ; đã dùng câu trả lời từ tài liệu.")
        return text.strip()

    @staticmethod
    def _responses_endpoint(base_url: str) -> str:
        """Append `/responses` without breaking a proxy URL query string."""
        parts = urlsplit(base_url)
        path = parts.path.rstrip("/")
        if not path.endswith("/responses"):
            path = f"{path}/responses"
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))

    @staticmethod
    def _output_text(body: dict) -> str:
        direct = body.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        parts = []
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    parts.append(content["text"])
        return "\n".join(parts)
