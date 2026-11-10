from math import ceil


class TokenEstimator:
    """Estimación local reproducible; no sustituye al tokenizador remoto."""

    _CHARACTERS_PER_TOKEN = 3

    def estimate(self, text: str) -> int:
        if not isinstance(text, str):
            raise ValueError("El texto debe ser una cadena.")
        if not text:
            return 0
        return ceil(len(text) / self._CHARACTERS_PER_TOKEN)

    @staticmethod
    def compaction_threshold(max_tokens: int) -> int:
        if max_tokens <= 0:
            raise ValueError("El presupuesto de memoria debe ser positivo.")
        return ceil(max_tokens * 0.9)

    @staticmethod
    def compaction_target(max_tokens: int) -> int:
        if max_tokens <= 0:
            raise ValueError("El presupuesto de memoria debe ser positivo.")
        return max(1, max_tokens // 2)
