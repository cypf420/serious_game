from serious_game_backend.application.ports import ResearchOutboxRepository


class ResearchOutboxService:
    def __init__(self, repository: ResearchOutboxRepository) -> None:
        self._repository = repository

    def drain(self, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("outbox limit must be between 1 and 1000")
        return self._repository.drain(limit)
