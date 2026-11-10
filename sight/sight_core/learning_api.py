"""Owner-session learning endpoints; all mutations use the existing scoped grants."""
import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Literal
from fastapi import HTTPException
from pydantic import Field
from .brain_store import BrainStore
from .memory import MemoryService, MemoryInput, MemoryEdit, MemoryDelete
from .forge import Forge, SkillManifest, SkillGenerate, SkillPromote, SkillSelect
from .jobs import Jobs, Job, JobSelect, RolePolicy
from .tools import StrictModel
from .releases import Releases
from .knowledge import (
    DenseVectorizer,
    HierarchicalMemoryCoordinator,
    MemoryManagementEngine,
    ProjectMemoryService,
    RAGEngine,
)
from .rsi import (
    RecursiveSelfImprovementEngine,
    PROTECTED_CORE_FILES,
    CapabilityGap,
    GapType,
    DiagnosticReport,
)


class RSISynthesizeInput(StrictModel):
    user_request: str = Field(min_length=3, max_length=500)
    suggested_tool_name: str = Field(min_length=2, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    missing_capability: str = Field(min_length=3, max_length=500)
    project_id: str = Field(default='default', pattern=r'^[A-Za-z0-9_-]{1,80}$')


class RSIAutoHealInput(StrictModel):
    skill_id: str = Field(min_length=2, max_length=80)
    error_type: str = Field(min_length=1, max_length=80)
    error_message: str = Field(min_length=1, max_length=500)
    failing_code: str = Field(min_length=10, max_length=50000)


class Compact(StrictModel):
    ids: list[str] = Field(min_length=1,max_length=20)
    project_id: str = Field(default='default',pattern=r'^[A-Za-z0-9_-]{1,80}$')


class ForgetSkill(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_.-]{2,79}$')


class Empty(StrictModel):pass


class Restore(StrictModel):
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')


class ProjectMemoryInput(StrictModel):
    project_id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]{1,80}$')
    category: Literal['goal', 'decision', 'architecture', 'choice', 'progress', 'issue', 'dependency', 'roadmap', 'file'] = 'decision'
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=12000)
    importance: int = Field(default=3, ge=1, le=5)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expiry: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectMemoryDelete(StrictModel):
    project_id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]{1,80}$')
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')


class RAGIngestInput(StrictModel):
    project_id: str = Field(default='default', pattern=r'^[A-Za-z0-9_-]{1,80}$')
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=500000)
    doc_format: Literal['txt', 'markdown', 'pdf', 'docx', 'csv', 'json', 'code', 'unknown'] = 'markdown'
    strategy: Literal['sliding_window', 'semantic_paragraph', 'hierarchical_markdown', 'code_aware'] = 'semantic_paragraph'
    metadata: dict[str, Any] = Field(default_factory=dict)


class RAGDocumentDelete(StrictModel):
    project_id: str = Field(default='default', pattern=r'^[A-Za-z0-9_-]{1,80}$')
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')


class VerifiableDelete(StrictModel):
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    project_id: str | None = None


ACTIONS={
    'memory/save':MemoryInput,'memory/edit':MemoryEdit,'memory/delete':MemoryDelete,
    'memory/purge':Empty,'memory/compact':Compact,
    'projects/add':ProjectMemoryInput,'projects/delete':ProjectMemoryDelete,
    'rag/ingest':RAGIngestInput,'rag/delete':RAGDocumentDelete,
    'memory/verifiable_delete':VerifiableDelete,
    'rsi/synthesize':RSISynthesizeInput,'rsi/promote':SkillPromote,'rsi/rollback':SkillSelect,'rsi/auto_heal':RSIAutoHealInput,
    'forge/stage':SkillManifest,'forge/generate':SkillGenerate,'forge/promote':SkillPromote,
    'forge/rollback':SkillSelect,'forge/archive':SkillSelect,'forge/forget':ForgetSkill,
    'jobs/submit':Job,'jobs/cancel':JobSelect,'jobs/pause':JobSelect,'jobs/resume':JobSelect,'roles/configure':RolePolicy,
    'backup':Empty,'restore':Restore,'releases/snapshot':Empty,'releases/select':Restore,
}


class Learning:
    def __init__(self, config, files, router):
        self.error=None;self.jobs=None
        try:
            self.store=BrainStore(config.data_dir)
            self.memory=MemoryService(self.store);self.forge=Forge(self.store)
            self.jobs=Jobs(self.store,self.memory,self.forge,files,router)
            self.vectorizer = DenseVectorizer()
            self.project_memory = ProjectMemoryService(self.store, vectorizer=self.vectorizer)
            self.rag = RAGEngine(self.store, vectorizer=self.vectorizer)
            self.manager = MemoryManagementEngine(self.store, vectorizer=self.vectorizer)
            self.hierarchical_memory = HierarchicalMemoryCoordinator(
                self.store,
                memory_service=self.memory,
                project_memory=self.project_memory,
                rag_engine=self.rag,
                manager=self.manager,
                vectorizer=self.vectorizer,
            )
            self.rsi = RecursiveSelfImprovementEngine(store=self.store, router=router)
        except (sqlite3.Error,ValueError,OSError):
            self.error='Learning storage unavailable. Existing data was preserved; restore a verified backup into a new data directory.'
        self.router=router
        self.releases=Releases(config.data_dir)

    def require(self):
        if self.error:raise HTTPException(503,self.error)

    def validate(self,path,args):
        if not path.startswith('/api/learning/'):return None
        self.require();key=path.removeprefix('/api/learning/')
        if key not in ACTIONS:raise ValueError('Unknown learning operation')
        value=ACTIONS[key].model_validate(args)
        if isinstance(value,Job):self.jobs.validate(value)
        summary={'backup':'Create an integrity-checked snapshot of learning, procedures and task receipts.',
                 'restore':'Restore the selected backup to a new isolated directory for inspection. Running data is preserved.',
                 'forge/generate':'Ask the configured model for a restricted text skill draft and test it; promotion requires a separate review.',
                 'forge/promote':'Promote this exact tested skill digest as a new immutable version.',
                 'jobs/submit':'Run this exact task plan within its displayed tool/model budgets. File writes create new workspace files only.',
                 'memory/delete':'Forget this memory and its derived summaries. Historical task receipts and separate backups are retained.',
                 'memory/verifiable_delete':'Verifiably purge memory from database and search indices with cryptographic proof.',
                 'projects/add':'Record a structured, isolated project memory entry.',
                 'projects/delete':'Delete an isolated project memory entry.',
                 'rag/ingest':'Ingest and index document into the multi-format RAG corpus.',
                 'rag/delete':'Remove a document and its chunks from the RAG index.',
                 'rsi/synthesize':'Synthesize a verified tool from capability gap and test in sandbox.',
                 'rsi/promote':'Promote a verified synthesized skill to immutable procedure registry.',
                 'rsi/rollback':'Roll back an active skill to a prior verified version.',
                 'rsi/auto_heal':'Diagnose runtime exception and synthesize surgical repair with rollback journal.',
                 'forge/forget':'Delete all versions and candidates of this skill; keep historical operational receipts.'}.get(key,'Apply the displayed '+key+' change to your local learning data.')
        return value.model_dump(),summary

    async def execute(self,path,args):
        self.require();key=path.removeprefix('/api/learning/')
        if key=='memory/save':return self.memory.put(MemoryInput.model_validate(args))
        if key=='memory/edit':
            identifier=args.pop('id');return self.memory.put(MemoryInput.model_validate(args),identifier)
        if key=='memory/delete':return self.memory.delete(args['id'])
        if key=='memory/purge':return self.memory.purge_expired()
        if key=='memory/compact':return self.memory.compact(args['ids'],args['project_id'])
        if key=='projects/add':
            p_in = ProjectMemoryInput.model_validate(args)
            rec = self.project_memory.add_record(
                project_id=p_in.project_id,
                category=p_in.category,
                title=p_in.title,
                content=p_in.content,
                importance=p_in.importance,
                confidence=p_in.confidence,
                expiry=p_in.expiry,
                metadata=p_in.metadata,
            )
            return rec.model_dump()
        if key=='projects/delete':
            return {'deleted': self.project_memory.delete_record(args['project_id'], args['id'])}
        if key=='rag/ingest':
            r_in = RAGIngestInput.model_validate(args)
            doc = self.rag.ingest_text(
                title=r_in.title,
                text=r_in.text,
                project_id=r_in.project_id,
                doc_format=r_in.doc_format,
                strategy=r_in.strategy,
                metadata=r_in.metadata,
            )
            return doc.model_dump()
        if key=='rag/delete':
            return {'deleted': self.rag.delete_document(args['id'], args['project_id'])}
        if key=='memory/verifiable_delete':
            return self.manager.verifiable_delete(args['id'], args.get('project_id'))
        if key=='rsi/synthesize':
            s_in = RSISynthesizeInput.model_validate(args)
            gap = CapabilityGap(
                id=f"gap-{uuid.uuid4().hex[:8]}",
                user_request=s_in.user_request,
                detected_intent="tool_synthesis",
                gap_type=GapType.USER_REQUESTED_EXTENSION,
                missing_capability=s_in.missing_capability,
                suggested_tool_name=s_in.suggested_tool_name,
                context={'project_id': s_in.project_id},
            )
            candidate = self.rsi.synthesizer.synthesize_tool_template(gap)
            test_res = self.rsi.synthesizer.run_tests(candidate)
            cid = None
            if test_res.passed and self.store:
                cid = self.rsi._save_candidate(candidate, test_res)
            return {
                'candidate_id': cid,
                'candidate': candidate.model_dump(),
                'test_results': test_res.model_dump(),
                'ready_for_promotion': test_res.passed,
            }
        if key=='rsi/promote':
            return self.rsi.promote_candidate(args['candidate_id'], args['expected_digest'])
        if key=='rsi/rollback':
            return self.rsi.rollback_skill(args['id'], args['version'])
        if key=='rsi/auto_heal':
            h_in = RSIAutoHealInput.model_validate(args)
            diag = DiagnosticReport(
                error_type=h_in.error_type,
                exception_message=h_in.error_message,
                failing_file="tool.py",
                sanitized_traceback=h_in.error_message,
                is_protected_core=False,
                diagnosis=f"Reported {h_in.error_type}: {h_in.error_message}",
            )
            res = self.rsi.auto_heal.attempt_skill_heal(h_in.skill_id, h_in.failing_code, diag)
            return res.model_dump()
        if key=='forge/stage':return await asyncio.to_thread(self.forge.stage,SkillManifest.model_validate(args))
        if key=='forge/generate':return await self.forge.generate(SkillGenerate.model_validate(args),self.router)
        if key=='forge/promote':return self.forge.promote(**args)
        if key=='forge/rollback':return self.forge.rollback(args['id'],args['version'])
        if key=='forge/archive':return self.forge.archive(args['id'],args['version'])
        if key=='forge/forget':return self.forge.forget(args['id'])
        if key=='jobs/submit':return self.jobs.submit(Job.model_validate(args))
        if key=='jobs/cancel':return self.jobs.cancel(args['id'])
        if key=='jobs/pause':return self.jobs.pause(args['id'])
        if key=='jobs/resume':return self.jobs.resume(args['id'])
        if key=='roles/configure':self.store.set_setting('role.'+args['role'],args);return args
        if key=='releases/snapshot':return self.releases.snapshot()
        if key=='releases/select':return self.releases.select(args['id'])
        if key=='backup':
            identifier=str(uuid.uuid4());return {'id':identifier}|self.store.backup(self.store.root/'backups'/(identifier+'.sqlite3'))
        if key=='restore':
            destination=self.store.root/'restores'/str(uuid.uuid4())
            restored=BrainStore.restore(self.store.root/'backups'/(args['id']+'.sqlite3'),destination)
            return {'restored':True,'directory':str(restored.root),'activated':False,'instruction':'Inspect the restored data, then launch with BEL_DATA_DIR set to this directory; configure the local model separately.'}
        raise ValueError('Unknown operation')

    def status(self):
        if self.error:return {'enabled':False,'status':'storage_error','reason':self.error,'growth_proven':False}
        return {'enabled':True,'status':'ready','stores':['profile','episodic_document','procedural','operational'],
                'workers':1,'logical_roles':12,'growth_proven':False,'benchmark':'See the measured build evidence; no automatic personal-growth claim.',
                'forge_scope':'declarative text transformations','external_code_execution':False}

    def mount(self,app):
        @app.get('/api/learning/releases')
        async def releases():self.require();return {'items':self.releases.list(),'activation':'Review first, then restart BEL with the verified source or release; no automatic promotion.'}

        @app.get('/api/learning/benchmark')
        async def benchmark():
            path=Path(__file__).resolve().parents[1]/'reports/growth_benchmark.json'
            if not path.is_file():return {'status':'not_run','growth_proven':False}
            return json.loads(path.read_text(encoding='utf-8'))

        @app.get('/api/learning/memory')
        async def memory(project_id:str='default',q:str=''):
            self.require();return {'items':self.memory.search(q,project_id,50) if q else self.memory.export(project_id)}

        @app.get('/api/learning/memory/unified')
        async def unified_memory(project_id: str = 'default', q: str = ''):
            self.require()
            return {'items': [r.model_dump() for r in self.hierarchical_memory.retrieve(q, project_id)]}

        @app.get('/api/learning/memory/{identifier}')
        async def record(identifier:str):
            self.require();row=self.memory.get(identifier)
            if not row:raise HTTPException(404,'Memory is absent or expired')
            return row

        @app.get('/api/learning/export')
        async def export(project_id:str='default'):
            self.require();return {'memory':self.memory.export(project_id),'procedural':self.forge.list(project_id),
                                   'operational':[j for j in self.jobs.list() if j['definition']['project_id']==project_id],
                                   'scope':'Current unexpired memory, procedures and last 100 tasks; retained operational receipts may quote earlier inputs.'}

        @app.get('/api/learning/skills')
        async def skills(project_id:str='default'):
            self.require()
            with self.store.connect() as db:
                candidates=[dict(r)|{'manifest':json.loads(r['manifest']),'tests':json.loads(r['tests'])} for r in db.execute("SELECT * FROM candidates WHERE json_extract(manifest,'$.project_id')=? ORDER BY created_at DESC LIMIT 100",(project_id,))]
            return {'items':self.forge.list(project_id),'candidates':candidates,'curator':self.forge.curator()}

        @app.get('/api/learning/jobs')
        async def jobs():self.require();return {'items':self.jobs.list()}

        @app.get('/api/learning/jobs/{identifier}')
        async def job(identifier:str):
            self.require();row=self.jobs.get(identifier)
            if not row:raise HTTPException(404,'Task not found')
            return row

        @app.get('/api/learning/roles')
        async def roles():self.require();return {'items':self.jobs.roles()}

        @app.get('/api/learning/events')
        async def events():self.require();return {'items':self.store.events()}

        @app.get('/api/learning/graph')
        async def graph(project_id:str='default'):
            self.require()
            nodes=[{'id':r['id'],'label':r['key'],'kind':r['store']} for r in self.memory.export(project_id)]
            nodes += [{'id':f'skill:{r["id"]}:{r["version"]}','label':r['id']+' v'+str(r['version']),'kind':'skill'} for r in self.forge.list(project_id)]
            nodes += [{'id':j['id'],'label':j['definition']['title'],'kind':'task'} for j in self.jobs.list() if j['definition']['project_id']==project_id]
            ids={n['id'] for n in nodes}
            with self.store.connect() as db:
                edges=[dict(e) for e in db.execute('SELECT * FROM graph_edges') if e['source'] in ids and e['target'] in ids]
                reviews=[dict(r) for r in db.execute('SELECT * FROM reviews ORDER BY created_at DESC LIMIT 50')]
            return {'nodes':nodes,'edges':edges,'reviews':reviews,'metrics':self.forge.curator()}

        @app.get('/api/learning/projects/{project_id}/records')
        async def project_records(project_id: str):
            self.require()
            return {'items': [r.model_dump() for r in self.project_memory.get_all_project_records(project_id)]}

        @app.get('/api/learning/projects/{project_id}/search')
        async def project_search(project_id: str, q: str = ''):
            self.require()
            hits = self.project_memory.search(project_id, q)
            return {'items': [{'record': r.model_dump(), 'score': s} for r, s in hits]}

        @app.get('/api/learning/rag/documents')
        async def rag_documents(project_id: str = 'default'):
            self.require()
            return {'items': [d.model_dump() for d in self.rag.list_documents(project_id)]}

        @app.get('/api/learning/rag/search')
        async def rag_search(project_id: str = 'default', q: str = ''):
            self.require()
            return {'items': [c.model_dump() for c in self.rag.search(q, project_id)]}

        @app.get('/api/learning/rsi/status')
        async def rsi_status():
            self.require()
            return {
                'enabled': True,
                'protected_core_files': sorted(list(PROTECTED_CORE_FILES)),
                'axioms': ['Human life, wellbeing, dignity, and safety always take priority over AI self-preservation.'],
                'curator': self.forge.curator(),
            }
