from pydantic import BaseModel, Field


class Dimension(BaseModel):
    name: str
    description: str = ""
    approved: bool = False


class KPI(BaseModel):
    name: str
    dimension: str = ""
    unit: str = ""
    description: str = ""
    approved: bool = False


class Intervention(BaseModel):
    name: str
    target_kpi: str = ""
    description: str = ""
    approved: bool = False


class ExtractionResult(BaseModel):
    dimensions: list[Dimension] = Field(default_factory=list)
    kpis: list[KPI] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)


class MergedExtraction(BaseModel):
    dimensions: list[Dimension] = Field(default_factory=list)
    kpis: list[KPI] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)

    def add(self, result: ExtractionResult) -> None:
        self.dimensions.extend(result.dimensions)
        self.kpis.extend(result.kpis)
        self.interventions.extend(result.interventions)
