"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CalendarIcon, Loader2, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ParticipantsInput } from "@/components/participants-input";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { useCreateMeeting, useUpdateMeeting } from "@/hooks/use-meetings";
import { ApiError, parseAgenda } from "@/lib/api";
import {
  formatTime,
  parseIsoDay,
  toIsoDate,
  toIsoWithOffset,
} from "@/lib/datetime";
import type {
  ActionItem,
  AgendaItem,
  AiSuggestion,
  Meeting,
  MeetingCreateInput,
} from "@/lib/types";

const timePattern = /^([01]\d|2[0-3]):([0-5]\d)$/;

const participantSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Name is required")
    .max(120, "Name is too long"),
  email: z
    .string()
    .trim()
    .max(255)
    .refine((value) => value === "" || z.email().safeParse(value).success, {
      message: "Enter a valid email address",
    })
    .optional(),
});

const formSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(1, "Name is required")
      .max(200, "Name is too long"),
    description: z
      .string()
      .trim()
      .max(2000, "Description is too long")
      .optional(),
    location: z.string().trim().max(200, "Location is too long").optional(),
    date: z.date(),
    startTime: z.string().regex(timePattern, "Use HH:mm"),
    endTime: z.string().regex(timePattern, "Use HH:mm"),
    participants: z.array(participantSchema).max(50, "At most 50 participants"),
  })
  .refine((data) => data.endTime > data.startTime, {
    message: "The meeting must end after it starts",
    path: ["endTime"],
  })
  .refine(
    (data) => {
      const keys = data.participants.map(
        (p) =>
          `${p.name.trim().toLowerCase()}|${(p.email ?? "").trim().toLowerCase()}`,
      );
      return new Set(keys).size === keys.length;
    },
    { message: "Participants must be unique", path: ["participants"] },
  );

type FormValues = z.infer<typeof formSchema>;

type ParticipantErrors = {
  name?: { message?: string };
  email?: { message?: string };
};

/** Flattens react-hook-form's per-row participant errors into { rowIndex: message }. */
function participantErrors(rows: unknown): Record<number, string | undefined> {
  if (!Array.isArray(rows)) return {};
  return Object.fromEntries(
    rows.map((row: ParticipantErrors | undefined, index: number) => [
      index,
      row?.name?.message ?? row?.email?.message,
    ]),
  );
}

/** Blank form for a new meeting, or the meeting's current values when editing. */
function defaultValues(meeting?: Meeting): FormValues {
  if (!meeting) {
    return {
      name: "",
      description: "",
      location: "",
      date: new Date(),
      startTime: "10:00",
      endTime: "11:00",
      participants: [{ name: "", email: "" }],
    };
  }
  return {
    name: meeting.name,
    description: meeting.description ?? "",
    location: meeting.location ?? "",
    date: parseIsoDay(meeting.starts_at),
    startTime: formatTime(meeting.starts_at),
    endTime: formatTime(meeting.ends_at),
    participants:
      meeting.participants.length > 0
        ? meeting.participants.map((p) => ({
            name: p.name,
            email: p.email ?? "",
          }))
        : [{ name: "", email: "" }],
  };
}

function parseStartsAt(startsAt: string): { date?: Date; time?: string } {
  let date: Date | undefined;
  let time: string | undefined;

  const dateMatch = /(\d{4}-\d{2}-\d{2})/.exec(startsAt);
  if (dateMatch) {
    const [y, m, d] = dateMatch[1].split("-").map(Number);
    const parsed = new Date(y, m - 1, d);
    if (!isNaN(parsed.getTime())) {
      date = parsed;
    }
  }

  const timeMatch = /(?:T|\s|^)(\d{2}:\d{2})/.exec(startsAt);
  if (timeMatch && timePattern.test(timeMatch[1])) {
    time = timeMatch[1];
  }

  return { date, time };
}

function calculateEndTime(startTime: string, durationMinutes: number): string {
  const [h, m] = startTime.split(":").map(Number);
  const totalMinutes = h * 60 + m + Math.max(1, durationMinutes);
  let endH = Math.floor(totalMinutes / 60);
  let endM = totalMinutes % 60;
  if (endH >= 24) {
    endH = 23;
    endM = 59;
  }
  return `${String(endH).padStart(2, "0")}:${String(endM).padStart(2, "0")}`;
}

function formatAgendaDescription(
  items: AgendaItem[] = [],
  actionItems: ActionItem[] = [],
): string {
  const parts: string[] = [];

  if (items && items.length > 0) {
    const agendaLines = items.map((item) => {
      const details: string[] = [];
      if (item.owner) details.push(item.owner);
      if (item.minutes) details.push(`${item.minutes}m`);
      const meta = details.length > 0 ? ` (${details.join(", ")})` : "";
      return `• ${item.topic}${meta}`;
    });
    parts.push(`Agenda:\n${agendaLines.join("\n")}`);
  }

  if (actionItems && actionItems.length > 0) {
    const actionLines = actionItems.map((item) => {
      const details: string[] = [];
      if (item.owner) details.push(item.owner);
      if (item.due) details.push(`due: ${item.due}`);
      const meta = details.length > 0 ? ` (${details.join(", ")})` : "";
      return `• ${item.task}${meta}`;
    });
    parts.push(`Action Items:\n${actionLines.join("\n")}`);
  }

  return parts.join("\n\n");
}

function SuggestedBadge() {
  return (
    <span className="tint-violet inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium leading-none">
      <Sparkles className="size-3" aria-hidden />
      suggested
    </span>
  );
}

function MeetingFormContent({
  meeting,
  onClose,
}: {
  meeting?: Meeting;
  onClose: () => void;
}) {
  const createMeeting = useCreateMeeting();
  const updateMeeting = useUpdateMeeting();
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const isEdit = !!meeting;

  // AI Agenda parser states
  const [pastedText, setPastedText] = useState("");
  const [isParsing, setIsParsing] = useState(false);
  const [parseProgress, setParseProgress] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [aiSuggestion, setAiSuggestion] = useState<AiSuggestion | null>(
    meeting?.ai_suggestion ?? null,
  );
  const [suggestedFields, setSuggestedFields] = useState<Record<string, boolean>>({});
  const abortControllerRef = useRef<AbortController | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: defaultValues(meeting),
  });

  const {
    register,
    handleSubmit,
    control,
    setError,
    formState: { errors, isSubmitting },
  } = form;

  const clearSuggested = (fieldName: string) => {
    setSuggestedFields((prev) => {
      if (!prev[fieldName]) return prev;
      const next = { ...prev };
      delete next[fieldName];
      return next;
    });
  };

  // Abort in-flight parsing on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsParsing(false);
    setParseProgress(null);
    toast.info("Parsing cancelled");
  };

  const handleParse = async () => {
    const text = pastedText.trim();
    if (!text) {
      toast.error("Please enter some agenda text to parse.");
      return;
    }

    if (text.length > 10000) {
      const msg = "Agenda text is too long (maximum 10,000 characters).";
      setParseError(msg);
      toast.error(msg);
      return;
    }

    setParseError(null);
    setIsParsing(true);
    setParseProgress("Analyzing agenda with AI…");

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const todayIso = toIsoDate(new Date());
      const tz =
        (typeof Intl !== "undefined"
          ? Intl.DateTimeFormat().resolvedOptions().timeZone
          : "UTC") || "UTC";

      const result = await parseAgenda({
        text,
        today: todayIso,
        tz,
        signal: controller.signal,
      });

      const suggestion: AiSuggestion = {
        agenda: result.agenda,
        model: result.model,
        prompt_version: result.prompt_version,
      };
      setAiSuggestion(suggestion);

      const newlySuggested: Record<string, boolean> = {};
      const agenda = result.agenda;

      if (agenda.title?.trim()) {
        form.setValue("name", agenda.title.trim(), { shouldValidate: true });
        newlySuggested.name = true;
      }

      if (agenda.starts_at) {
        const { date: parsedDate, time: parsedTime } = parseStartsAt(
          agenda.starts_at,
        );
        if (parsedDate) {
          form.setValue("date", parsedDate, { shouldValidate: true });
          newlySuggested.date = true;
        }
        if (parsedTime) {
          form.setValue("startTime", parsedTime, { shouldValidate: true });
          newlySuggested.startTime = true;

          const duration = agenda.duration_minutes ?? 60;
          const endTime = calculateEndTime(parsedTime, duration);
          form.setValue("endTime", endTime, { shouldValidate: true });
          newlySuggested.endTime = true;
        }
      }

      const desc = formatAgendaDescription(
        agenda.items,
        agenda.action_items,
      );
      if (desc.trim()) {
        form.setValue("description", desc.trim(), { shouldValidate: true });
        newlySuggested.description = true;
      }

      const owners = new Set<string>();
      for (const item of agenda.items || []) {
        if (item.owner?.trim()) owners.add(item.owner.trim());
      }
      for (const action of agenda.action_items || []) {
        if (action.owner?.trim()) owners.add(action.owner.trim());
      }

      if (owners.size > 0) {
        const participants = Array.from(owners).map((name) => ({
          name,
          email: "",
        }));
        form.setValue("participants", participants, { shouldValidate: true });
        newlySuggested.participants = true;
      }

      setSuggestedFields(newlySuggested);
      toast.success("Agenda parsed successfully!");
    } catch (err: unknown) {
      if (
        (err instanceof DOMException && err.name === "AbortError") ||
        (err instanceof Error && err.name === "AbortError")
      ) {
        return;
      }

      let message = "Could not parse agenda.";
      if (err instanceof ApiError) {
        if (err.status === 413 || err.code === "text_too_long") {
          message = "Agenda text is too long (limit is 10,000 characters).";
        } else if (err.status === 422 || err.code === "parse_failed") {
          message = "Could not parse an agenda from the provided text.";
        } else if (err.status === 429 || err.code === "throttled") {
          message = "Too many requests. Please wait a moment and try again.";
        } else if (err.status === 0 || err.code === "network_error") {
          message = "Network error: could not reach the agenda parser.";
        } else {
          message = err.message || message;
        }
      } else if (err instanceof Error) {
        message = err.message;
      }

      setParseError(message);
      toast.error(message);
    } finally {
      setIsParsing(false);
      setParseProgress(null);
      abortControllerRef.current = null;
    }
  };

  const onSubmit = handleSubmit(async (values) => {
    const participants = values.participants
      .filter((participant) => participant.name.trim() !== "")
      .map((participant) => ({
        name: participant.name.trim(),
        email: participant.email?.trim() ? participant.email.trim() : null,
      }));

    const payload: MeetingCreateInput = {
      name: values.name.trim(),
      description: values.description?.trim() || null,
      location: values.location?.trim() || null,
      starts_at: toIsoWithOffset(values.date, values.startTime),
      ends_at: toIsoWithOffset(values.date, values.endTime),
      participants,
      ai_suggestion: aiSuggestion ?? null,
    };

    try {
      if (meeting) {
        await updateMeeting.mutateAsync({ id: meeting.id, payload });
        toast.success("Meeting updated");
      } else {
        await createMeeting.mutateAsync(payload);
        toast.success("Meeting created");
      }
      onClose();
    } catch (error) {
      if (error instanceof ApiError) {
        // Map server-side field errors back onto the matching inputs.
        const fieldMap: Record<string, keyof FormValues> = {
          name: "name",
          description: "description",
          location: "location",
          starts_at: "startTime",
          ends_at: "endTime",
          participants: "participants",
        };
        for (const detail of error.details) {
          const target = fieldMap[detail.field.split(".")[0] ?? ""];
          if (target) setError(target, { message: detail.message });
        }
        toast.error(error.message);
      } else {
        toast.error(
          isEdit
            ? "Could not update the meeting."
            : "Could not create the meeting.",
        );
      }
    }
  });

  return (
    <>
      <DialogHeader>
        <DialogTitle>{isEdit ? "Edit meeting" : "New meeting"}</DialogTitle>
        <DialogDescription>
          {isEdit
            ? "Change the details, time slot or participants."
            : "Give it a name, a time slot and the people who should be there."}
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Left Column: Paste an agenda */}
        <div className="flex flex-col space-y-4 rounded-xl border border-border/70 bg-card/60 p-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2 font-semibold text-sm">
              <Sparkles className="size-4 text-violet-500" />
              <span>Paste an agenda</span>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">
              Paste raw text from an email, invite, or notes. The AI will
              extract the title, times, agenda items, and participants.
            </p>
          </div>

          <div className="flex flex-1 flex-col space-y-2">
            <Label htmlFor="pastedAgenda" className="sr-only">
              Paste an agenda
            </Label>
            <Textarea
              id="pastedAgenda"
              rows={8}
              placeholder={`Paste an agenda or meeting notes here…\n\nExample:\nTeam sync next Monday 10am-11am.\nAgenda:\n- Architecture review (Alex, 30m)\n- Release schedule (Dana, 20m)\nAction items:\n- Send meeting summary (Alex, due: tomorrow)`}
              value={pastedText}
              onChange={(e) => {
                setPastedText(e.target.value);
                if (parseError) setParseError(null);
              }}
              disabled={isParsing}
              className="flex-1 min-h-[180px] resize-y text-xs sm:text-sm font-sans"
            />
          </div>

          {parseError ? (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-destructive text-xs">
              {parseError}
            </div>
          ) : null}

          {isParsing ? (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/60 p-2.5">
              <div className="flex items-center gap-2 text-muted-foreground text-xs sm:text-sm animate-pulse">
                <Loader2 className="size-4 animate-spin text-primary" />
                <span>{parseProgress ?? "Parsing agenda with AI…"}</span>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleCancel}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-2 pt-1">
              <span className="text-muted-foreground text-xs">
                {pastedText.length > 0
                  ? `${pastedText.length.toLocaleString()} / 10,000`
                  : ""}
              </span>
              <Button
                type="button"
                size="sm"
                onClick={handleParse}
                disabled={!pastedText.trim() || isParsing}
                className="tint-violet hover:opacity-90 font-medium"
              >
                <Sparkles className="size-3.5 mr-1" />
                Parse
              </Button>
            </div>
          )}
        </div>

        {/* Right Column: Existing agenda form */}
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="name">Name</Label>
              {suggestedFields.name ? <SuggestedBadge /> : null}
            </div>
            <Input
              id="name"
              placeholder="Sprint planning"
              aria-invalid={!!errors.name}
              aria-describedby={errors.name ? "name-error" : undefined}
              {...register("name", {
                onChange: () => clearSuggested("name"),
              })}
            />
            {errors.name ? (
              <p id="name-error" className="text-destructive text-sm">
                {errors.name.message}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="description">Description</Label>
              {suggestedFields.description ? <SuggestedBadge /> : null}
            </div>
            <Textarea
              id="description"
              rows={3}
              placeholder="What is this meeting about?"
              {...register("description", {
                onChange: () => clearSuggested("description"),
              })}
            />
            {errors.description ? (
              <p className="text-destructive text-sm">
                {errors.description.message}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="location">Location</Label>
              {suggestedFields.location ? <SuggestedBadge /> : null}
            </div>
            <Input
              id="location"
              placeholder="Room 3 or a meeting link"
              {...register("location", {
                onChange: () => clearSuggested("location"),
              })}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2 sm:col-span-1">
              <div className="flex items-center justify-between">
                <Label>Date</Label>
                {suggestedFields.date ? <SuggestedBadge /> : null}
              </div>
              <Controller
                control={control}
                name="date"
                render={({ field }) => (
                  <Popover
                    open={datePickerOpen}
                    onOpenChange={setDatePickerOpen}
                  >
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full justify-start font-normal"
                      >
                        <CalendarIcon className="size-4" aria-hidden />
                        {toIsoDate(field.value)}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-0" align="start">
                      <Calendar
                        mode="single"
                        selected={field.value}
                        onSelect={(date) => {
                          if (date) {
                            clearSuggested("date");
                            field.onChange(date);
                          }
                          setDatePickerOpen(false);
                        }}
                        autoFocus
                      />
                    </PopoverContent>
                  </Popover>
                )}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="startTime">Start</Label>
                {suggestedFields.startTime ? <SuggestedBadge /> : null}
              </div>
              <Input
                id="startTime"
                type="time"
                step={900}
                {...register("startTime", {
                  onChange: () => clearSuggested("startTime"),
                })}
              />
              {errors.startTime ? (
                <p className="text-destructive text-sm">
                  {errors.startTime.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="endTime">End</Label>
                {suggestedFields.endTime ? <SuggestedBadge /> : null}
              </div>
              <Input
                id="endTime"
                type="time"
                step={900}
                {...register("endTime", {
                  onChange: () => clearSuggested("endTime"),
                })}
              />
              {errors.endTime ? (
                <p className="text-destructive text-sm">
                  {errors.endTime.message}
                </p>
              ) : null}
            </div>
          </div>

          <Controller
            control={control}
            name="participants"
            render={({ field }) => (
              <ParticipantsInput
                value={field.value}
                onChange={(val) => {
                  clearSuggested("participants");
                  field.onChange(val);
                }}
                errors={participantErrors(errors.participants)}
                badge={suggestedFields.participants ? <SuggestedBadge /> : null}
              />
            )}
          />
          {errors.participants?.message ? (
            <p className="text-destructive text-sm">
              {errors.participants.message}
            </p>
          ) : null}

          <DialogFooter className="pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isEdit
                ? isSubmitting
                  ? "Saving…"
                  : "Save changes"
                : isSubmitting
                  ? "Creating…"
                  : "Create meeting"}
            </Button>
          </DialogFooter>
        </form>
      </div>
    </>
  );
}

/** Creates a meeting, or edits `meeting` when one is passed. */
export function MeetingFormDialog({
  open,
  onOpenChange,
  meeting,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  meeting?: Meeting;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-4xl lg:max-w-5xl">
        {open ? (
          <MeetingFormContent
            key={meeting?.id ?? "new"}
            meeting={meeting}
            onClose={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
