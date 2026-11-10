import { useQueryClient } from "@tanstack/react-query";
import { FolderPlus, Loader2, MessageCircleQuestion, Send, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";

import { api, thumbnailUrl } from "@/api/client";
import { useConnection, useQuestion, useQuestions, useTask, useVlmStatus } from "@/api/hooks";
import type { AskAnswer } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLibraryState } from "@/library/state";
import { cn } from "@/lib/utils";

/**
 * Ask the library in plain language. The local model turns the question into filters,
 * the program looks them up and counts, and the model answers from what it found,
 * citing photos as [n].
 */
export function AskView() {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const queryClient = useQueryClient();
  const vlm = useVlmStatus();
  const history = useQuestions();
  const [draft, setDraft] = useState("");
  const [current, setCurrent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const question = useQuestion(current);
  const installed =
    !!vlm.data?.runtime_installed &&
    vlm.data.models.some((m) => m.role === "default" && m.downloaded);

  const status = question.data?.status;
  useEffect(() => {
    if (status && status !== "pending")
      void queryClient.invalidateQueries({ queryKey: ["ask"], exact: true });
  }, [status, queryClient]);

  const ask = (text: string) => {
    if (!conn || !text.trim()) return;
    setError(null);
    api
      .askLibrary(conn, text.trim(), i18n.language)
      .then((asked) => {
        setCurrent(asked.id);
        setDraft("");
        void queryClient.invalidateQueries({ queryKey: ["ask"], exact: true });
      })
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    ask(draft);
  };
  const remove = (id: number) => {
    if (!conn) return;
    void api.deleteQuestion(conn, id).then(() => {
      if (current === id) setCurrent(null);
      void queryClient.invalidateQueries({ queryKey: ["ask"], exact: true });
    });
  };
  const examples = t("ask.examples").split("|");
  const pending = status === "pending";

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="shrink-0 space-y-2 px-6 pb-3 pt-4">
          <form onSubmit={submit} className="flex max-w-3xl gap-2">
            <div className="relative flex-1">
              <MessageCircleQuestion className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-highlight" />
              <Input
                value={draft}
                autoFocus
                aria-label={t("ask.placeholder")}
                placeholder={t("ask.placeholder")}
                onChange={(event) => setDraft(event.target.value)}
                className="h-10 pl-9 text-[14px]"
                disabled={!installed}
              />
            </div>
            <Button type="submit" className="h-10" disabled={!installed || pending || !draft.trim()}>
              {pending ? <Loader2 className="animate-spin" /> : <Send />}
              {t("ask.submit")}
            </Button>
          </form>
          {vlm.data && !installed && (
            <p className="text-[12px] text-warning">{t("ask.notInstalled")}</p>
          )}
          {installed && current === null && (
            <div className="flex flex-wrap gap-1.5">
              {examples.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => ask(example)}
                  className="rounded-full border border-white/10 px-3 py-1 text-[12px] text-muted-foreground hover:border-white/25 hover:text-foreground"
                >
                  {example}
                </button>
              ))}
            </div>
          )}
          {error && (
            <p role="alert" className="text-[12px] text-destructive">
              {error}
            </p>
          )}
          <p className="text-[11px] text-subtle-foreground">{t("ask.privacy")}</p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          {question.data && <AnswerView answer={question.data} />}
        </div>
      </div>

      <aside
        aria-label={t("ask.history")}
        className="hidden w-64 shrink-0 flex-col border-l border-white/10 lg:flex"
      >
        <h2 className="px-4 pb-1 pt-4 text-[12px] font-medium text-muted-foreground">
          {t("ask.history")}
        </h2>
        <ol className="min-h-0 flex-1 overflow-y-auto pb-3">
          {history.data?.map((item) => (
            <li key={item.id} className="group flex items-center">
              <button
                type="button"
                onClick={() => setCurrent(item.id)}
                aria-current={current === item.id || undefined}
                className={cn(
                  "min-w-0 flex-1 truncate px-4 py-1.5 text-left text-[12.5px] hover:bg-white/5",
                  current === item.id && "bg-white/10",
                  item.status === "failed" && "text-muted-foreground line-through",
                )}
              >
                {item.question}
              </button>
              <button
                type="button"
                aria-label={t("ask.delete", { question: item.question })}
                onClick={() => remove(item.id)}
                className="mr-2 rounded p-1 text-muted-foreground opacity-0 hover:bg-white/10 hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
              >
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}

/** [n] in the answer → a link to the n-th photo. */
function withCitations(text: string) {
  return text.replace(/\[(\d{1,3})\](?!\()/g, "[[$1]](#photo-$1)");
}

function AnswerView({ answer }: { answer: AskAnswer }) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const { openViewer, openCollect } = useLibraryState();
  const task = useTask(answer.status === "pending" ? answer.task_id : null);
  const plan = answer.plan;
  const stats = answer.stats;
  const keywords = plan?.keywords ?? [];
  const groups = stats?.groups ?? [];
  const ids = answer.asset_ids;
  const open = (index: number) => {
    const item = answer.items[index];
    if (item) openViewer(ids, item.id);
  };
  const understood = plan
    ? [
        plan.date_from || plan.date_to
          ? t("ask.planDates", { from: plan.date_from || "…", to: plan.date_to || "…" })
          : "",
        plan.country,
        plan.city,
        plan.camera,
        plan.lens,
        plan.min_rating ? "★".repeat(plan.min_rating) : "",
        plan.favorite ? t("ask.planFavorite") : "",
        plan.media_type ? t(plan.media_type === "video" ? "ask.planVideos" : "ask.planPhotos") : "",
        keywords.length ? t("ask.planKeywords", { words: keywords.join("、") }) : "",
        plan.visual ? t("ask.planVisual", { text: plan.visual }) : "",
      ].filter(Boolean)
    : [];
  const steps = [t("ask.stepUnderstand"), t("ask.stepLookUp"), t("ask.stepAnswer")];

  return (
    <article aria-label={answer.question} className="max-w-4xl space-y-4">
      <h2 className="text-[16px] font-medium">{answer.question}</h2>
      {answer.status === "pending" && (
        <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          {task.data?.status === "running"
            ? steps[Math.min(task.data.progress_current, 2)]
            : t("ask.queued")}
        </p>
      )}
      {answer.status === "failed" && (
        <p role="alert" className="text-[12.5px] text-destructive">
          {t("ask.failed")} {answer.error}
        </p>
      )}
      {understood.length > 0 && (
        <p className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <span>{t("ask.understood")}</span>
          {understood.map((part) => (
            <span key={part} className="rounded bg-white/5 px-1.5 py-0.5 text-foreground/80">
              {part}
            </span>
          ))}
        </p>
      )}
      {answer.answer && (
        <div className="prose-lumen select-text text-[14px] leading-relaxed">
          <Markdown
            components={{
              a: ({ href, children }) => {
                const match = /^#photo-(\d+)$/.exec(href ?? "");
                return match ? (
                  <button
                    type="button"
                    onClick={() => open(Number(match[1]) - 1)}
                    className="mx-0.5 rounded bg-highlight/20 px-1 text-[0.85em] text-highlight hover:bg-highlight/30"
                  >
                    {children}
                  </button>
                ) : (
                  <a href={href}>{children}</a>
                );
              },
            }}
          >
            {withCitations(answer.answer)}
          </Markdown>
        </div>
      )}
      {stats && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-subtle-foreground">
          <span>{t("ask.total", { count: stats.total })}</span>
          {keywords.length > 0 && (
            <span>{t("ask.described", { count: stats.described })}</span>
          )}
          {stats.visual_used && <span>{t("ask.visualUsed")}</span>}
        </div>
      )}
      {groups.length > 0 && (
        <ol aria-label={t("ask.groups")} className="max-w-md space-y-1">
          {groups.map((group) => (
            <li key={group.label} className="flex items-center gap-2 text-[12px]">
              <span className="w-28 shrink-0 truncate">{group.label}</span>
              <span
                className="h-2 rounded-sm bg-highlight/70"
                style={{ width: `${(100 * group.count) / groups[0]!.count}%` }}
              />
              <span className="shrink-0 text-muted-foreground">
                {new Intl.NumberFormat(i18n.language).format(group.count)}
              </span>
            </li>
          ))}
        </ol>
      )}
      {answer.items.length > 0 && conn && (
        <section aria-label={t("ask.photos")} className="space-y-2">
          <div className="flex items-center gap-2">
            <h3 className="text-[12.5px] font-medium">{t("ask.photos")}</h3>
            <Button variant="ghost" size="sm" className="ml-auto" onClick={() => openCollect(ids)}>
              <FolderPlus /> {t("ask.addAll", { count: ids.length })}
            </Button>
          </div>
          <ol className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2">
            {answer.items.map((item, index) => (
              <li key={item.id} className="relative">
                <button
                  type="button"
                  aria-label={`[${index + 1}] ${item.file_name}`}
                  onClick={() => open(index)}
                  className="block aspect-square w-full overflow-hidden rounded-md bg-black/40"
                >
                  <img
                    src={thumbnailUrl(conn, item.id, item.rendition_version)}
                    alt=""
                    loading="lazy"
                    className="size-full object-cover"
                  />
                </button>
                <span className="pointer-events-none absolute left-1 top-1 rounded bg-black/65 px-1 text-[10px] text-white">
                  {index + 1}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </article>
  );
}
