"use client";
import { resolveCharacter } from "./lib/characters";
import { useEffect, useRef, useState } from "react";

export type ReferenceDocument = { id: string; title: string; category: string; status: string; body: string; version?: number | string; can_reference: boolean; reference_unavailable_reason?: string; story_day?: number; source_kind?: string; related_npc_ids?: string[] };
const categories: Record<string, string> = { archive: "调查与证据", meeting: "会议与听证", document: "正式公文", housing_plan: "房源配置说明" };
const statuses: Record<string, string> = { discussion: "讨论中", resolved: "已形成结论", published: "已公布", pending_countersign: "待会签", aborted: "已中止", completed: "已完成", active: "进行中", cancelled: "已中止", draft: "草案", issued: "已签发", signed: "已签发", read: "已查阅", passed: "已通过", rejected: "未通过", approved: "已批准", pending_review: "待审查" };
export function referenceStatus(doc: ReferenceDocument) { return statuses[doc.status] || doc.status; }
export function ReferenceInput({ value, onChange, documents, selected, onSelected, disabled, placeholder, error }: { value: string; onChange: (value: string) => void; documents: ReferenceDocument[]; selected: string[]; onSelected: (ids: string[]) => void; disabled: boolean; placeholder: string; error?: string }) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [query, setQuery] = useState<{ start: number; end: number; text: string } | null>(null);
  const [active, setActive] = useState(0);
  const candidates = useRef<HTMLDivElement>(null);
  useEffect(() => { candidates.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" }); }, [active, query?.text]);
  const choices = documents.filter(doc => !selected.includes(doc.id) && doc.title.toLocaleLowerCase().includes((query?.text || "").toLocaleLowerCase())).slice(0, 12);
  function inspect(text: string, caret: number) {
    const match = /@([^@\s]*)$/.exec(text.slice(0, caret));
    setQuery(match ? { start: caret - match[0].length, end: caret, text: match[1] } : null); setActive(0);
  }
  function choose(doc: ReferenceDocument) {
    if (disabled || !doc.can_reference || selected.length >= 8) return;
    onSelected([...selected, doc.id]);
    if (query) onChange(value.slice(0, query.start) + value.slice(query.end));
    setQuery(null); input.current?.focus();
  }
  return <div className="reference-composer">
    <div className="reference-tags" aria-label="已引用文件">{selected.map(id => { const doc = documents.find(item => item.id === id); return <span key={id}>@{doc?.title || "档案"} · {doc ? referenceStatus(doc) : "待核验"}{doc?.version != null ? ` · 版本 ${doc.version}` : ""}<button type="button" disabled={disabled} aria-label={`移除引用 ${doc?.title || "档案"}`} onClick={() => onSelected(selected.filter(item => item !== id))}>×</button></span>; })}</div>
    <textarea ref={input} name="player_text" value={value} disabled={disabled} maxLength={1000} placeholder={placeholder + " 输入 @ 引用档案"} onChange={event => { onChange(event.target.value); inspect(event.target.value, event.target.selectionStart); }} onClick={event => inspect(value, event.currentTarget.selectionStart)} onKeyDown={event => {
      if (event.nativeEvent.isComposing || !query) return;
      if (event.key === "Escape") { event.preventDefault(); setQuery(null); }
      if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); setActive(index => Math.max(0, Math.min(choices.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))); }
      if (event.key === "Enter" && choices[active]) { event.preventDefault(); choose(choices[active]); }
    }} aria-controls="reference-candidates" />
    {query && <div ref={candidates} className="reference-candidates" id="reference-candidates" role="listbox" aria-label="选择引用档案">{selected.length >= 8 ? <p>每次最多引用8份档案，请先移除一份。</p> : choices.length ? choices.map((doc, index) => <button type="button" role="option" aria-selected={index === active} key={doc.id} disabled={disabled || !doc.can_reference} onClick={() => choose(doc)}><b>{doc.title}</b><small>{doc.story_day != null ? `第 ${doc.story_day} 日 · ` : ""}{doc.can_reference ? referenceStatus(doc) : doc.reference_unavailable_reason || "当前对话不能引用此文件"}{doc.version != null ? ` · 版本 ${doc.version}` : ""}</small></button>) : <p>{error || "没有匹配的可引用档案。未读材料需先从行动中查阅。"}</p>}</div>}
  </div>;
}
export function ReferenceLibrary({ documents, loading, error, onRetry, onReference }: { documents: ReferenceDocument[]; loading: boolean; error: string; onRetry: () => void; onReference?: (id: string) => void }) {
  const [search, setSearch] = useState("");
  return <section className="reference-library" aria-label="档案系统"><h3>档案系统</h3><p>已查阅材料与会议形成的记录统一保存在这里。对话引用不会代替实际办理；合同仍仅可应用符合条件的会议红头文件。</p><label>查找文件<input value={search} onChange={event => setSearch(event.target.value)} placeholder="输入文件名称" /></label>{loading && <p role="status">正在读取档案…</p>}{error && <p role="alert">{error}<button type="button" onClick={onRetry}>重新加载</button></p>}
    {Object.entries(categories).map(([category, title]) => <section key={category}><h4>{title}</h4>{documents.filter(doc => (doc.id.split(":")[0] === category) && doc.title.includes(search)).map(doc => <details key={doc.id}><summary>{doc.title} <small>{referenceStatus(doc)}{doc.version != null ? ` · 版本 ${doc.version}` : ""}</small></summary><p>来源：{categories[doc.source_kind || doc.id.split(":")[0]] || "档案"}{doc.story_day != null ? ` · 第 ${doc.story_day} 日` : ""}{doc.related_npc_ids?.length ? ` · 关联人物：${doc.related_npc_ids.map(id => resolveCharacter(id)?.name || "相关人员").join("、")}` : ""}</p><p className="reference-body">{doc.body || "尚未形成正文。"}</p>{onReference && <><button type="button" disabled={loading || !doc.can_reference} onClick={() => onReference(doc.id)}>在当前对话中引用</button>{!doc.can_reference && <p>{doc.reference_unavailable_reason || "当前对话不能引用此文件"}</p>}</>}</details>)}</section>)}{!loading && !error && !documents.length && <p>暂无已查阅材料或已形成的会议文件。首次查档仍请前往“行动—查阅档案”。</p>}
  </section>;
}

export function ReferenceAttachments({ references }: { references: unknown }) {
  const items = Array.isArray(references) ? references.filter(item => item && typeof item === "object" && typeof item.id === "string") : [];
  if (!items.length) return null;
  return <span className="reference-attachments" aria-label="本轮引用文件">{items.map((item, index) => <span key={`${item.id}:${index}`}>引用：{typeof item.title === "string" ? item.title : "档案"}{item.version != null ? ` · 当时版本 ${String(item.version)}` : " · 版本未记录"}{typeof item.status === "string" ? ` · ${statuses[item.status] || item.status}` : ""}</span>)}</span>;
}
