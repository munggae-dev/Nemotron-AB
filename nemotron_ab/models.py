from dataclasses import dataclass


@dataclass
class PersonaFilter:
    sex: str
    age_min: int
    age_max: int
    province: str
    district: str


@dataclass
class JobPayload:
    title: str
    text_a: str
    text_b: str
    context: str
    profile: str
    evaluator: str
    llm_base_url: str
    llm_model: str
    max_personas: int
    retrieval_k_per_bucket: int
    eval_concurrency: int
    persona_filter: PersonaFilter


@dataclass
class JobSummary:
    id: int
    status: str
    title: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    error_message: str | None
