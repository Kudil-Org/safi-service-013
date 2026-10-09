from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InstantiateRequest(BaseModel):
    template: str = "openapi-service"
    manifest: Dict[str, Any]
    instance_id: Optional[str] = None
    sow: Optional[Dict[str, Any]] = None
    repo: Optional[str] = None
    branch: Optional[str] = None
    sha: Optional[str] = None
    openapi: Optional[str] = None
    acceptance_tests: Optional[List[str]] = None


class IngestRequest(BaseModel):
    category: str
    content: str = Field(min_length=1)
    source: str = Field(min_length=1)
    verification_status: str
    repo: Optional[str] = None
    branch: Optional[str] = None
    observed_at_sha: Optional[str] = None
    allowed_roles: Optional[List[str]] = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class GitStateModel(BaseModel):
    repo: str
    branch: str = ""
    sha: str = ""
    manifest_sha: Optional[str] = None
    sha_matches_manifest: Optional[bool] = None
    dirty: bool = False
    commits: List[Dict[str, Any]] = Field(default_factory=list)
    files: List[str] = Field(default_factory=list)


class KnowledgeItem(BaseModel):
    knowledge_id: str
    service_expert_id: str
    category: str
    content: str
    source: str
    verification_status: str
    allowed_roles: List[str]
    repo: Optional[str] = None
    branch: Optional[str] = None
    observed_at_sha: Optional[str] = None
    created_at: str
    sha_status: Optional[str] = None


class InstantiateResponse(BaseModel):
    instance_id: str
    template: str
    service: Dict[str, Any]
    git: GitStateModel
    manifest: Dict[str, Any]
    seeded_knowledge: int
    created_at: str


class ContextRef(BaseModel):
    knowledge_id: str
    category: str
    verification_status: str
    observed_at_sha: Optional[str] = None
    sha_status: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    instance_id: str
    question: str
    answer: str
    roles: List[str]
    permitted_categories: List[str]
    context_items: List[ContextRef]
    llm_mode: str
    endpoint_configured: bool
    created_at: str


class InstanceResponse(BaseModel):
    instance_id: str
    template: str
    service: Dict[str, Any]
    manifest: Dict[str, Any]
    git: GitStateModel
    roles: List[str]
    knowledge_counts: Dict[str, int]
    knowledge: List[KnowledgeItem]
    created_at: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    llm_configured: bool
    db: str
