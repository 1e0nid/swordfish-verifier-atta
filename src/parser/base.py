from abc import ABC, abstractmethod
from src.models.rules import SpecificationRules


class BaseParser(ABC):

    @abstractmethod
    def parse(self, target_path: str) -> SpecificationRules:
        pass
