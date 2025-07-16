import asyncio
from datetime import datetime
from typing import Optional, List

from loguru import logger as log
from propcache import cached_property
from sqlalchemy import JSON as SA_JSON
from sqlmodel import Field, SQLModel
from sqlmodel import select

from back_end import receptionist
from back_end.receptionist import rr
from mileslib_infra import Project


class Organization(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str

    website_url: Optional[str] = None
    blog_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    facebook_url: Optional[str] = None

    primary_phone: Optional[dict] = Field(default=None, sa_type=SA_JSON)
    languages: Optional[List[str]] = Field(default=None, sa_type=SA_JSON)
    phone: Optional[str] = None
    linkedin_uid: Optional[str] = None

    founded_year: Optional[int] = Field(default=None, index=True)
    logo_url: Optional[str] = None
    primary_domain: Optional[str] = Field(default=None, index=True)
    owned_by_organization_id: Optional[str] = Field(default=None, index=True)

    organization_revenue_printed: Optional[str] = None
    organization_revenue: float = 0.0

    organization_headcount_six_month_growth: Optional[float] = None
    organization_headcount_twelve_month_growth: Optional[float] = None
    organization_headcount_twenty_four_month_growth: Optional[float] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    def __repr__(self):
        return f"{self.name}"

    @classmethod
    def from_dict(cls, data: dict):
        keys = cls.__fields__.keys()  # pydantic v1
        return cls(**{k: v for k, v in data.items() if k in keys})


class Contact(SQLModel, table=True):
    id: str = Field(primary_key=True)

    first_name: str
    last_name: Optional[str]
    name: str
    email: Optional[str] = None
    email_status: Optional[str] = None

    title: Optional[str] = None
    headline: Optional[str] = None

    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    github_url: Optional[str] = None
    facebook_url: Optional[str] = None
    photo_url: Optional[str] = None

    extrapolated_email_confidence: Optional[float] = None
    organization_id: Optional[str] = Field(default=None)

    def __repr__(self):
        return f"{self.name}"

    @classmethod
    def from_dict(cls, data: dict):
        keys = cls.__fields__.keys()  # pydantic v1
        return cls(**{k: v for k, v in data.items() if k in keys})


class Apollo:
    def __init__(self, _project: Project):
        self.project = _project
        _ = self.api, self.db
        log.success(f"{self}: Successfully Initialized!")

    def __repr__(self):
        return f"[{self.project.name}.Apollo]"

    @cached_property
    def api(self):
        return receptionist.API.from_config(self.project, "apollo")

    @cached_property
    def db(self):
        db = self.api.receptionist.db
        log.debug(f"{self} SQLModel Sanity Check: {SQLModel.metadata.tables.keys()}")
        log.debug(f"{self} DB Path Sanity Check: {db.server.db_path}")
        SQLModel.metadata.create_all(db.engine)
        return db

    def search_org(self, org_name: str) -> List[Organization] | Organization:
        with self.db.session() as s:
            row = s.exec(select(Organization).where(Organization.name == org_name)).first()
            if row:
                log.debug(f"{self}: Row detected: {row}")
                return row

        data: rr = asyncio.run(self.api.receptionist.post("search_by_org_name", append=org_name))
        raw = data.content["organizations"]
        orgs = [Organization.from_dict(obj) for obj in raw]

        for org in orgs:
            self.get_contacts(org)

        with self.db.session() as s:
            s.add_all(orgs)
            row = s.exec(select(Organization).where(Organization.name == org_name)).first()
            if row:
                log.debug(f"{self}: Row detected: {row}")
                return row

        return orgs[0] if len(orgs) == 1 else orgs

    def get_contacts(self, org: Organization) -> List[Contact] | Contact:
        log.debug(f"{self}: Populating contacts for {org.name}")
        data: rr = asyncio.run(self.api.receptionist.post("get_contacts", append=org.id))
        raw = data.content["people"]
        contacts = [Contact.from_dict(obj) for obj in raw]

        with self.db.session() as s:
            s.add_all(contacts)

        return contacts[0] if len(contacts) == 1 else contacts
