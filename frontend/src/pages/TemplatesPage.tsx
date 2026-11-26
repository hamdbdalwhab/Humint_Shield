/**
 * Email template gallery — Arabic-first, Midnight Cyber edition.
 *
 * The page is a real catalogue, not a mock: every card is backed by the
 * organization's template records, thumbnails render the actual inline-CSS
 * email inside a sandboxed iframe, and the preview dialog renders the
 * personalised email produced by the backend for a real employee.
 */
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import FormControlLabel from '@mui/material/FormControlLabel';
import Grid from '@mui/material/Grid';
import InputAdornment from '@mui/material/InputAdornment';
import MenuItem from '@mui/material/MenuItem';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { alpha } from '@mui/material/styles';
import { motion } from 'framer-motion';
import {
  ChevronDown,
  Code2,
  Eye,
  FileText,
  Layers,
  Mail,
  MessageCircle,
  MessageSquare,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Wand2,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';

import { aiApi, brandingApi, employeesApi, templatesApi } from '@/api/endpoints';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { EmailVisualEditor } from '@/components/email-editor/EmailVisualEditor';
import { renderEmailDesignHtml } from '@/components/email-editor/renderEmail';
import { createDefaultDesign, legacyDesign } from '@/components/email-editor/types';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import type {
  AIGeneratedTemplate,
  EmailDesign,
  EmailTemplate,
  EmailTemplateCreate,
  TemplateTestSendResult,
} from '@/types';

const VARIABLES = [
  'first_name',
  'last_name',
  'email',
  'department',
  'company_name',
  'manager_name',
  'invoice_number',
  'meeting_time',
  'tracking_url',
];

const DEFAULT_BODY = `<p>Dear {{first_name}},</p>
<p>Please review the attached document before our meeting.</p>
<p><a href="{{tracking_url}}">Open document</a></p>
<p>Regards,<br/>{{company_name}}</p>`;

const DEFAULT_TEXT = `مرحباً {{first_name}}،

لديك مستند تدريبي أمني جديد يحتاج مراجعتك قبل نهاية اليوم.

افتح المستند: {{tracking_url}}

{{company_name}}`;

interface TemplateFormValues {
  name: string;
  subject: string;
  body_html: string;
  channel: 'email' | 'sms' | 'whatsapp';
  difficulty_level: number;
  is_active: boolean;
}

const EMPTY_TEMPLATE: TemplateFormValues = {
  name: '',
  subject: '',
  body_html: DEFAULT_BODY,
  channel: 'email',
  difficulty_level: 5,
  is_active: true,
};

const CHANNEL_META: Record<
  'email' | 'sms' | 'whatsapp',
  { label: string; color: string; icon: typeof Mail }
> = {
  email: { label: 'بريد', color: '#00F0FF', icon: Mail },
  sms: { label: 'SMS', color: '#FFB020', icon: MessageSquare },
  whatsapp: { label: 'واتساب', color: '#25D366', icon: MessageCircle },
};

function applySampleVariables(html: string): string {
  return html
    .replace(/\{\{first_name\}\}/g, 'Jane')
    .replace(/\{\{last_name\}\}/g, 'Doe')
    .replace(/\{\{email\}\}/g, 'jane.doe@company.com')
    .replace(/\{\{company_name\}\}/g, 'Acme Corporation')
    .replace(/\{\{department\}\}/g, 'Finance')
    .replace(/\{\{manager_name\}\}/g, 'Omar Hassan')
    .replace(/\{\{invoice_number\}\}/g, 'INV-2026-8841')
    .replace(/\{\{meeting_time\}\}/g, 'Thursday, 10:30 AM')
    .replace(/\{\{tracking_url\}\}/g, '#');
}

function plainText(value: string): string {
  return value
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|li|tr|h[1-6]|blockquote)>/gi, '\n')
    .replace(/<li\b[^>]*>/gi, '• ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/[ \t]+/g, ' ')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function previewDocument(html: string): string {
  if (/<html[\s>]/i.test(html)) return html;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" /></head><body style="margin:0;background:#f2f4f7;font-family:Arial,sans-serif">${html}</body></html>`;
}

function localPreview(html: string): string {
  return previewDocument(applySampleVariables(html));
}

function ChannelChip({ channel }: { channel: 'email' | 'sms' | 'whatsapp' }) {
  const meta = CHANNEL_META[channel] ?? CHANNEL_META.email;
  const Icon = meta.icon;
  return (
    <Chip
      size="small"
      icon={<Icon size={11} />}
      label={meta.label}
      variant="outlined"
      sx={{
        height: 21,
        fontSize: '0.61rem',
        fontWeight: 800,
        color: meta.color,
        borderColor: `${meta.color}55`,
        bgcolor: `${meta.color}12`,
      }}
    />
  );
}

function TemplateThumbnail({ template }: { template: EmailTemplate }) {
  return (
    <Box
      sx={{
        position: 'relative',
        height: 178,
        overflow: 'hidden',
        bgcolor: '#f5f7fa',
        borderBottom: '1px solid rgba(255,255,255,.08)',
        '&::after': {
          content: '""',
          position: 'absolute',
          inset: 0,
          background: 'linear-gradient(180deg, transparent 55%, rgba(10,15,28,.32))',
          pointerEvents: 'none',
        },
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          top: 12,
          left: '50%',
          width: 600,
          height: 400,
          transform: 'translateX(-50%) scale(.45)',
          transformOrigin: 'top center',
          borderRadius: 1.5,
          overflow: 'hidden',
          bgcolor: '#fff',
          boxShadow: '0 8px 30px rgba(0,0,0,.16)',
        }}
      >
        <iframe
          title={`${template.name} thumbnail`}
          srcDoc={localPreview(template.body_html)}
          sandbox=""
          loading="lazy"
          style={{ width: 600, height: 400, border: 0, pointerEvents: 'none' }}
        />
      </Box>
      <Chip
        size="small"
        icon={template.is_built_in ? <Sparkles size={11} /> : <Code2 size={11} />}
        label={template.is_built_in ? 'أساسي' : 'مخصص'}
        sx={{
          position: 'absolute',
          top: 10,
          insetInlineEnd: 10,
          zIndex: 2,
          bgcolor: template.is_built_in ? 'rgba(0,240,255,.12)' : 'rgba(112,0,255,.16)',
          border: `1px solid ${template.is_built_in ? 'rgba(0,240,255,.32)' : 'rgba(157,77,255,.34)'}`,
          color: template.is_built_in ? 'primary.main' : '#C9A7FF',
          fontSize: '0.62rem',
          fontWeight: 800,
          backdropFilter: 'blur(6px)',
        }}
      />
    </Box>
  );
}

export function TemplatesPage() {
  const { organizationId, user } = useAuth();
  const queryClient = useQueryClient();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<EmailTemplate | null>(null);
  const [design, setDesign] = useState<EmailDesign | null>(null);
  const [testResult, setTestResult] = useState<TemplateTestSendResult | null>(null);
  const [previewTemplate, setPreviewTemplate] = useState<EmailTemplate | null>(null);
  const [previewEmployeeId, setPreviewEmployeeId] = useState('');
  const [pendingDelete, setPendingDelete] = useState<EmailTemplate | null>(null);
  const [search, setSearch] = useState('');
  const [difficulty, setDifficulty] = useState('all');
  const [activeTab, setActiveTab] = useState<'all' | 'email' | 'sms' | 'whatsapp' | 'ai'>('all');
  const [aiDepartment, setAiDepartment] = useState('');
  const [aiScenario, setAiScenario] = useState('');
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiChannel, setAiChannel] = useState<'email' | 'sms'>('sms');
  const [aiResult, setAiResult] = useState<AIGeneratedTemplate | null>(null);
  const channelFilter = activeTab === 'ai' ? 'all' : activeTab;
  const bodyRef = useRef<HTMLTextAreaElement | null>(null);
  const form = useForm<TemplateFormValues>({ defaultValues: EMPTY_TEMPLATE });
  const editorChannel = form.watch('channel') ?? 'email';
  // SMS is a single segment: 170 characters including the {{link}} placeholder.
  const SMS_BODY_LIMIT = 170;
  const smsBodyText = plainText(form.watch('body_html') ?? '')
    .replace(/\s+/g, ' ')
    .trim();
  const smsLength = smsBodyText.length;
  const smsOverLimit = editorChannel === 'sms' && smsLength > SMS_BODY_LIMIT;

  const templatesQuery = useQuery({
    queryKey: ['templates', organizationId],
    queryFn: () => templatesApi.list(organizationId as string),
    enabled: Boolean(organizationId),
  });

  const brandingQuery = useQuery({
    queryKey: ['branding', organizationId],
    queryFn: () => brandingApi.get(organizationId as string),
    enabled: Boolean(organizationId),
  });
  const branding = brandingQuery.data ?? null;

  const designQuery = useQuery({
    queryKey: ['template-design', organizationId, editing?.id],
    queryFn: () => templatesApi.design(organizationId as string, editing?.id as string),
    enabled: Boolean(editorOpen && editing && !editing.design_json && organizationId),
  });

  useEffect(() => {
    if (!editorOpen || !editing) return;
    if (editing.design_json) {
      setDesign(editing.design_json);
    } else if (designQuery.data) {
      setDesign(designQuery.data);
    }
  }, [designQuery.data, editing, editorOpen]);

  useEffect(() => {
    if (!editorOpen || !design || editorChannel !== 'email') return;
    const nextBody =
      design.mode === 'legacy'
        ? design.legacy_html || ''
        : renderEmailDesignHtml(design, branding, { forEditor: false });
    if (nextBody !== form.getValues('body_html')) {
      form.setValue('body_html', nextBody, { shouldDirty: true });
    }
  }, [branding, design, editorChannel, editorOpen, form]);

  const employeesQuery = useQuery({
    queryKey: ['employees', organizationId, 'preview-picker'],
    queryFn: () => employeesApi.list(organizationId as string, { per_page: 200 }),
    enabled: Boolean(organizationId),
  });

  const saveMutation = useMutation({
    mutationFn: async (values: TemplateFormValues) => {
      if (!organizationId) throw new Error('No organization');
      const payload = {
        ...values,
        design_json: editorChannel === 'email' && design ? design : undefined,
      };
      if (editing) return templatesApi.update(organizationId, editing.id, payload);
      return templatesApi.create(organizationId, payload as EmailTemplateCreate);
    },
    onSuccess: () => {
      toast.success(editing ? 'تم تحديث القالب' : 'تم إنشاء القالب');
      setEditorOpen(false);
      setEditing(null);
      setDesign(null);
      setTestResult(null);
      void queryClient.invalidateQueries({ queryKey: ['templates'] });
      void queryClient.invalidateQueries({ queryKey: ['template-design'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const testSendMutation = useMutation({
    mutationFn: async () => {
      if (!organizationId) throw new Error('No organization');
      const subject = form.getValues('subject').trim();
      if (!subject) throw new Error('أضف موضوع الرسالة أولاً');
      return templatesApi.sendTest(organizationId, {
        subject,
        body_html: form.getValues('body_html'),
        design_json: design ?? undefined,
        channel: 'email',
      });
    },
    onSuccess: (result) => {
      setTestResult(result);
      if (result.success) {
        toast.success(`تم إرسال نسخة تجريبية إلى ${result.to_email}`);
      } else {
        toast.error(result.error || 'تعذّر إرسال النسخة التجريبية');
      }
    },
    onError: (error) => {
      const message = errorMessage(error);
      setTestResult({
        success: false,
        message_id: null,
        error: message,
        to_email: user?.email ?? '',
        preview_html: null,
      });
      toast.error(message);
    },
  });

  const aiMutation = useMutation({
    mutationFn: () =>
      aiApi.generateTemplate({
        target_department: aiDepartment.trim(),
        scenario: aiScenario.trim(),
        channel: form.getValues('channel'),
      }),
    onSuccess: (generated) => {
      const targetChannel = form.getValues('channel');
      // SMS/WhatsApp are plain segments: keep the editor in text mode instead
      // of replacing the body with the email HTML shell.
      const bodyValue =
        targetChannel === 'email' ? generated.body_html : plainText(generated.body_html);
      form.setValue('subject', generated.subject, { shouldDirty: true, shouldValidate: true });
      form.setValue('body_html', bodyValue, { shouldDirty: true, shouldValidate: true });
      form.setValue('difficulty_level', generated.difficulty_level, { shouldDirty: true });
      if (!form.getValues('name').trim()) {
        form.setValue('name', generated.subject.slice(0, 120), { shouldDirty: true });
      }
      if (targetChannel === 'email') {
        setDesign(legacyDesign(generated.body_html, branding?.primary_color));
      }
      setAiError(null);
      toast.success(`تم توليد القالب بالذكاء الاصطناعي (${generated.provider ?? 'AI'})`);
    },
    onError: (error) => {
      const message = errorMessage(error);
      setAiError(message);
      toast.error(message);
    },
  });

  // Dedicated "AI generator" tab: generate, review, then open or save.
  const aiGenerateMutation = useMutation({
    mutationFn: () =>
      aiApi.generateTemplate({
        target_department: aiDepartment.trim(),
        scenario: aiScenario.trim(),
        channel: aiChannel,
      }),
    onSuccess: (generated) => {
      setAiResult(generated);
      setAiError(null);
      toast.success(
        `تم التوليد (${generated.model || generated.provider || 'AI'}) — راجع النص قبل الحفظ`,
      );
    },
    onError: (error) => {
      const message = errorMessage(error);
      setAiResult(null);
      setAiError(message);
      toast.error(message);
    },
  });

  const aiSaveMutation = useMutation({
    mutationFn: async () => {
      if (!organizationId || !aiResult) throw new Error('لا يوجد قالب مولّد للحفظ');
      return templatesApi.create(organizationId, {
        name: aiResult.subject.slice(0, 120),
        subject: aiResult.subject,
        body_html: aiResult.body_html,
        channel: aiChannel,
        difficulty_level: aiResult.difficulty_level,
        is_active: true,
        design_json: aiChannel === 'email' ? legacyDesign(aiResult.body_html, branding?.primary_color) : null,
      } as EmailTemplateCreate);
    },
    onSuccess: () => {
      toast.success('تم حفظ القالب المولّد');
      setAiResult(null);
      void queryClient.invalidateQueries({ queryKey: ['templates'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  function openGeneratedInEditor() {
    if (!aiResult) return;
    openCreate();
    form.setValue('channel', aiChannel, { shouldDirty: true });
    form.setValue('name', aiResult.subject.slice(0, 120), { shouldDirty: true });
    form.setValue('subject', aiResult.subject, { shouldDirty: true });
    form.setValue('difficulty_level', aiResult.difficulty_level, { shouldDirty: true });
    form.setValue(
      'body_html',
      aiChannel === 'email' ? aiResult.body_html : plainText(aiResult.body_html),
      { shouldDirty: true },
    );
    setDesign(
      aiChannel === 'email' ? legacyDesign(aiResult.body_html, branding?.primary_color) : null,
    );
  }

  const deleteMutation = useMutation({
    mutationFn: async (template: EmailTemplate) => {
      if (!organizationId) throw new Error('No organization');
      await templatesApi.remove(organizationId, template.id);
    },
    onSuccess: () => {
      toast.success('تم حذف القالب');
      setPendingDelete(null);
      void queryClient.invalidateQueries({ queryKey: ['templates'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const previewQuery = useQuery({
    queryKey: ['template-preview', organizationId, previewTemplate?.id, previewEmployeeId],
    queryFn: () =>
      templatesApi.preview(organizationId as string, previewTemplate?.id as string, previewEmployeeId),
    enabled: Boolean(organizationId && previewTemplate && previewEmployeeId),
  });

  const templates = useMemo(() => templatesQuery.data ?? [], [templatesQuery.data]);
  const selectedPreviewEmployee = useMemo(
    () => employeesQuery.data?.items.find((item) => item.id === previewEmployeeId),
    [employeesQuery.data, previewEmployeeId],
  );

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return templates.filter((template) => {
      const matchesSearch =
        !needle ||
        template.name.toLowerCase().includes(needle) ||
        template.subject.toLowerCase().includes(needle);
      const matchesDifficulty = difficulty === 'all' || template.difficulty_level === Number(difficulty);
      const matchesChannel = channelFilter === 'all' || template.channel === channelFilter;
      return matchesSearch && matchesDifficulty && matchesChannel;
    });
  }, [templates, search, difficulty, channelFilter]);

  const channelCounts = useMemo(
    () => ({
      all: templates.length,
      email: templates.filter((template) => (template.channel ?? 'email') === 'email').length,
      sms: templates.filter((template) => template.channel === 'sms').length,
      whatsapp: templates.filter((template) => template.channel === 'whatsapp').length,
    }),
    [templates],
  );

  const stats = useMemo(
    () => ({
      total: templates.length,
      builtIn: templates.filter((template) => template.is_built_in).length,
      custom: templates.filter((template) => !template.is_built_in).length,
      active: templates.filter((template) => template.is_active).length,
    }),
    [templates],
  );

  const levelOptions = useMemo(
    () => [...new Set(templates.map((template) => template.difficulty_level))].sort((a, b) => a - b),
    [templates],
  );

  function insertVariable(variable: string) {
    const textarea = bodyRef.current;
    const token = `{{${variable}}}`;
    const current = form.getValues('body_html');
    if (!textarea) {
      form.setValue('body_html', `${current}${token}`);
      return;
    }
    const start = textarea.selectionStart ?? current.length;
    const end = textarea.selectionEnd ?? current.length;
    const next = `${current.slice(0, start)}${token}${current.slice(end)}`;
    form.setValue('body_html', next);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.selectionStart = start + token.length;
      textarea.selectionEnd = start + token.length;
    });
  }

  function openCreate() {
    setEditing(null);
    setAiDepartment('');
    setAiScenario('');
    setAiError(null);
    setTestResult(null);
    const initialDesign = createDefaultDesign(branding);
    setDesign(initialDesign);
    form.reset({
      ...EMPTY_TEMPLATE,
      body_html: renderEmailDesignHtml(initialDesign, branding, { forEditor: false }),
    });
    setEditorOpen(true);
  }

  function openEdit(template: EmailTemplate) {
    setEditing(template);
    setAiDepartment('');
    setAiScenario('');
    setAiError(null);
    setTestResult(null);
    setDesign(template.design_json ?? null);
    form.reset({
      name: template.name,
      subject: template.subject,
      body_html: template.body_html,
      channel: template.channel ?? 'email',
      difficulty_level: template.difficulty_level,
      is_active: template.is_active,
    });
    setEditorOpen(true);
  }

  function openPreview(template: EmailTemplate) {
    setPreviewTemplate(template);
    setPreviewEmployeeId((current) => current || employeesQuery.data?.items[0]?.id || '');
  }

  return (
    <>
      <PageHeader
        title="قوالب الرسائل"
        subtitle="مكتبة سيناريوهات تصيّد جاهزة، مبنية بـ HTML و CSS مضمّنين ومختبرة على عملاء البريد الحقيقيين."
        actions={
          <Button variant="contained" startIcon={<Plus size={17} />} onClick={openCreate}>
            قالب جديد
          </Button>
        }
      />

      <Box
        sx={{
          mb: 2.5,
          borderRadius: 3,
          border: '1px solid rgba(255,255,255,.08)',
          bgcolor: 'rgba(9,15,26,.6)',
          px: 1,
        }}
      >
        <Tabs
          value={activeTab}
          onChange={(_event, value) => setActiveTab(value)}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
          sx={{
            minHeight: 48,
            '& .MuiTab-root': {
              minHeight: 48,
              fontWeight: 800,
              fontSize: '0.82rem',
              gap: 0.5,
            },
            '& .Mui-selected': { color: 'primary.main' },
            '& .MuiTabs-indicator': {
              height: 3,
              borderRadius: 2,
              background: 'linear-gradient(90deg, #00F0FF, #7C4DFF)',
            },
          }}
        >
          <Tab value="all" icon={<Layers size={15} />} iconPosition="start" label={`كل القوالب (${channelCounts.all})`} />
          <Tab value="email" icon={<Mail size={15} />} iconPosition="start" label={`بريد إلكتروني (${channelCounts.email})`} />
          <Tab value="sms" icon={<MessageSquare size={15} />} iconPosition="start" label={`رسائل SMS (${channelCounts.sms})`} />
          <Tab value="whatsapp" icon={<MessageCircle size={15} />} iconPosition="start" label={`واتساب (${channelCounts.whatsapp})`} />
          <Tab value="ai" icon={<Wand2 size={15} />} iconPosition="start" label="المولّد الذكي" />
        </Tabs>
      </Box>

      {activeTab === 'ai' ? (
        <Box sx={{ maxWidth: 1000, mx: 'auto' }}>
          <Box
            sx={{
              p: { xs: 2, md: 2.5 },
              borderRadius: 4,
              border: '1px solid rgba(0,240,255,.20)',
              background:
                'radial-gradient(circle at 92% 0%, rgba(0,240,255,.12), transparent 44%), linear-gradient(145deg, rgba(20,35,58,.9), rgba(8,14,26,.9))',
            }}
          >
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
              <Wand2 size={18} color="#00F0FF" />
              <Typography sx={{ fontWeight: 800, fontSize: '1rem' }}>المولّد الذكي للرسائل</Typography>
              <Chip
                size="small"
                label="AI"
                sx={{
                  height: 20,
                  fontSize: '0.58rem',
                  fontWeight: 900,
                  color: '#00F0FF',
                  bgcolor: 'rgba(0,240,255,.1)',
                  border: '1px solid rgba(0,240,255,.28)',
                }}
              />
            </Stack>
            <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mb: 2 }}>
              اكتب السيناريو؛ يُستخدم قطاع مؤسستك تلقائياً. لرسائل SMS يولّد النموذج مقطعاً واحداً
              (≤170 حرفاً) يحتوي <code>{'{{link}}'}</code> فقط، بدون HTML بريدي. راجع الناتج قبل
              الحفظ — لا يُنشأ أي قالب تلقائياً.
            </Typography>

            <Grid container spacing={1.5}>
              <Grid item xs={12} sm={3}>
                <TextField
                  select
                  size="small"
                  fullWidth
                  label="القناة"
                  value={aiChannel}
                  onChange={(event) => setAiChannel(event.target.value as 'email' | 'sms')}
                  disabled={aiGenerateMutation.isPending}
                >
                  <MenuItem value="sms">SMS — مقطع واحد</MenuItem>
                  <MenuItem value="email">بريد إلكتروني</MenuItem>
                </TextField>
              </Grid>
              <Grid item xs={12} sm={4}>
                <TextField
                  size="small"
                  fullWidth
                  label="القسم المستهدف"
                  placeholder="مثال: IT أو المالية"
                  value={aiDepartment}
                  onChange={(event) => setAiDepartment(event.target.value)}
                  disabled={aiGenerateMutation.isPending}
                />
              </Grid>
              <Grid item xs={12} sm={5}>
                <TextField
                  size="small"
                  fullWidth
                  multiline
                  minRows={2}
                  label="السيناريو المطلوب"
                  placeholder="مثال: انتهاء جلسة VPN وتطلب إعادة التحقق"
                  value={aiScenario}
                  onChange={(event) => setAiScenario(event.target.value)}
                  disabled={aiGenerateMutation.isPending}
                />
              </Grid>
            </Grid>

            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={1.2}
              alignItems={{ xs: 'stretch', sm: 'center' }}
              sx={{ mt: 1.75 }}
            >
              <Button
                variant="contained"
                startIcon={
                  aiGenerateMutation.isPending ? (
                    <CircularProgress size={14} color="inherit" />
                  ) : (
                    <Sparkles size={16} />
                  )
                }
                disabled={
                  aiGenerateMutation.isPending || !aiDepartment.trim() || !aiScenario.trim()
                }
                onClick={() => {
                  setAiError(null);
                  aiGenerateMutation.mutate();
                }}
                sx={{
                  px: 3,
                  py: 1,
                  fontWeight: 900,
                  background: 'linear-gradient(135deg, #00F0FF 0%, #7C4DFF 100%)',
                  color: '#04101C',
                  '&:hover': { background: 'linear-gradient(135deg, #5CF6FF 0%, #9B75FF 100%)' },
                }}
              >
                {aiGenerateMutation.isPending ? 'جارٍ التوليد…' : 'توليد الرسالة'}
              </Button>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                يعبّئ الموضوع والجسم ومستوى الصعوبة تلقائياً. قد يستغرق حتى دقيقة.
              </Typography>
            </Stack>

            {aiError ? (
              <Alert
                severity="error"
                sx={{ mt: 1.75 }}
                action={
                  <Button
                    color="inherit"
                    size="small"
                    onClick={() => aiGenerateMutation.mutate()}
                    disabled={aiGenerateMutation.isPending}
                  >
                    إعادة المحاولة
                  </Button>
                }
              >
                <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.4 }}>
                  تعذّر توليد الرسالة
                </Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                  {aiError}
                </Typography>
              </Alert>
            ) : null}

            {aiResult ? (
              <Box
                sx={{
                  mt: 2,
                  p: { xs: 1.5, md: 2 },
                  borderRadius: 3,
                  border: '1px solid rgba(255,255,255,.10)',
                  bgcolor: 'rgba(255,255,255,.02)',
                }}
              >
                <Stack
                  direction={{ xs: 'column', sm: 'row' }}
                  justifyContent="space-between"
                  alignItems={{ xs: 'flex-start', sm: 'center' }}
                  spacing={1}
                  sx={{ mb: 1.25 }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                      الناتج — راجعه قبل الحفظ
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {aiResult.subject}
                    </Typography>
                  </Box>
                  <Stack direction="row" spacing={0.6} sx={{ flexWrap: 'wrap', gap: 0.6 }}>
                    <Chip size="small" variant="outlined" label={`L${aiResult.difficulty_level}`} />
                    <Chip
                      size="small"
                      variant="outlined"
                      color={aiChannel === 'sms' && plainText(aiResult.body_html).length > 170 ? 'error' : 'success'}
                      label={
                        aiChannel === 'sms'
                          ? `${plainText(aiResult.body_html).length} حرف`
                          : 'HTML بريدي'
                      }
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      label={aiResult.model || aiResult.provider || 'AI'}
                    />
                  </Stack>
                </Stack>

                {aiChannel === 'email' ? (
                  <Box
                    component="iframe"
                    title="AI generated preview"
                    sandbox=""
                    srcDoc={localPreview(aiResult.body_html)}
                    sx={{
                      width: '100%',
                      height: 320,
                      border: '1px solid rgba(255,255,255,.12)',
                      borderRadius: 2,
                      bgcolor: '#fff',
                    }}
                  />
                ) : (
                  <Box
                    sx={{
                      border: '1px solid rgba(255,255,255,.12)',
                      borderRadius: 2,
                      bgcolor: 'rgba(3,8,18,.82)',
                      p: 2,
                    }}
                  >
                    <Typography
                      component="pre"
                      sx={{
                        m: 0,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        fontFamily: 'Tahoma, Arial, sans-serif',
                        fontSize: '0.9rem',
                        lineHeight: 1.9,
                        color: '#EAF6FF',
                        direction: 'rtl',
                      }}
                    >
                      {plainText(applySampleVariables(aiResult.body_html))}
                    </Typography>
                  </Box>
                )}

                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mt: 1.75 }}>
                  <Button
                    variant="contained"
                    startIcon={<Pencil size={15} />}
                    onClick={openGeneratedInEditor}
                  >
                    فتح في المحرر
                  </Button>
                  <Button
                    variant="outlined"
                    startIcon={
                      aiSaveMutation.isPending ? (
                        <CircularProgress size={14} color="inherit" />
                      ) : (
                        <Plus size={15} />
                      )
                    }
                    disabled={aiSaveMutation.isPending}
                    onClick={() => aiSaveMutation.mutate()}
                  >
                    حفظ كقالب جديد
                  </Button>
                </Stack>
              </Box>
            ) : null}
          </Box>
        </Box>
      ) : (
        <>
      <Box
        sx={{
          mb: 2.5,
          p: { xs: 2, md: 2.5 },
          borderRadius: 4,
          border: '1px solid rgba(0,240,255,.14)',
          background:
            'radial-gradient(circle at 92% 0%, rgba(0,240,255,.11), transparent 40%), linear-gradient(145deg, rgba(22,33,55,.84), rgba(9,14,24,.82))',
          display: 'grid',
          gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' },
          gap: 1.25,
        }}
      >
        {[
          { label: 'إجمالي القوالب', value: stats.total, icon: <Layers size={16} />, color: '#00F0FF' },
          { label: 'قوالب أساسية', value: stats.builtIn, icon: <Sparkles size={16} />, color: '#B388FF' },
          { label: 'قوالب مخصصة', value: stats.custom, icon: <Wand2 size={16} />, color: '#FFB020' },
          { label: 'نشطة الآن', value: stats.active, icon: <Mail size={16} />, color: '#00E676' },
        ].map((item) => (
          <Stack key={item.label} direction="row" spacing={1.1} alignItems="center">
            <Box
              sx={{
                width: 38,
                height: 38,
                borderRadius: 2,
                display: 'grid',
                placeItems: 'center',
                color: item.color,
                bgcolor: alpha(item.color, 0.08),
                border: `1px solid ${alpha(item.color, 0.2)}`,
                flex: '0 0 auto',
              }}
            >
              {item.icon}
            </Box>
            <Box>
              <Typography sx={{ fontSize: '1.25rem', fontWeight: 800, lineHeight: 1 }}>{item.value}</Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.67rem' }}>
                {item.label}
              </Typography>
            </Box>
          </Stack>
        ))}
      </Box>

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1.25}
        alignItems={{ xs: 'stretch', md: 'center' }}
        sx={{ mb: 2.25 }}
      >
        <TextField
          size="small"
          placeholder="ابحث بالاسم أو الموضوع…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          sx={{ flex: 1, minWidth: 260 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Search size={16} />
              </InputAdornment>
            ),
          }}
        />
        <TextField
          select
          size="small"
          label="مستوى الصعوبة"
          value={difficulty}
          onChange={(event) => setDifficulty(event.target.value)}
          sx={{ minWidth: 170 }}
        >
          <MenuItem value="all">الكل</MenuItem>
          {levelOptions.map((level) => (
            <MenuItem key={level} value={String(level)}>
              مستوى {level}
            </MenuItem>
          ))}
        </TextField>
        <Typography variant="caption" sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}>
          عرض {filtered.length} من {templates.length}
        </Typography>
      </Stack>

      {templatesQuery.isLoading ? (
        <LoadingState label="جارٍ تحميل مكتبة القوالب…" />
      ) : templatesQuery.error ? (
        <Alert severity="error">{errorMessage(templatesQuery.error)}</Alert>
      ) : filtered.length === 0 ? (
        <Box
          sx={{
            p: 4,
            borderRadius: 4,
            border: '1px dashed rgba(255,255,255,.12)',
            background: 'rgba(255,255,255,.018)',
          }}
        >
          <EmptyState title="لا توجد قوالب مطابقة" description="جرّب بحثاً آخر أو أنشئ قالباً جديداً." />
        </Box>
      ) : (
        <Grid container spacing={2}>
          {filtered.map((template, index) => (
            <Grid item xs={12} sm={6} xl={4} key={template.id}>
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, delay: Math.min(index * 0.035, 0.4) }}
                style={{ height: '100%' }}
              >
                <Box
                  className="mc-template-card"
                  sx={{
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    borderRadius: 3.5,
                    overflow: 'hidden',
                    border: '1px solid rgba(255,255,255,.09)',
                    background: 'linear-gradient(160deg, rgba(24,35,57,.84), rgba(11,17,30,.9))',
                    boxShadow: '0 20px 50px rgba(0,0,0,.32)',
                    transition: 'transform .22s ease, border-color .22s ease, box-shadow .22s ease',
                    '&:hover': {
                      transform: 'translateY(-4px)',
                      borderColor: 'rgba(0,240,255,.30)',
                      boxShadow: '0 28px 70px rgba(0,0,0,.45), 0 0 30px rgba(0,240,255,.07)',
                    },
                  }}
                >
                  <TemplateThumbnail template={template} />
                  <Stack sx={{ p: 2, flex: 1 }} spacing={1.1}>
                    <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography sx={{ fontSize: '0.96rem', fontWeight: 800, lineHeight: 1.45 }}>
                          {template.name}
                        </Typography>
                        <Typography
                          variant="caption"
                          noWrap
                          title={template.subject}
                          sx={{ display: 'block', color: 'text.secondary', mt: 0.3 }}
                        >
                          {template.subject}
                        </Typography>
                      </Box>
                      <Stack direction="row" spacing={0.6} alignItems="center" sx={{ flex: '0 0 auto' }}>
                        <ChannelChip channel={template.channel ?? 'email'} />
                        <Chip
                          size="small"
                          label={`L${template.difficulty_level}`}
                          color={template.difficulty_level >= 8 ? 'error' : template.difficulty_level >= 4 ? 'warning' : 'success'}
                          variant="outlined"
                          sx={{ fontSize: '0.62rem', fontWeight: 800, flex: '0 0 auto' }}
                        />
                      </Stack>
                    </Stack>

                    <Stack direction="row" spacing={0.55} sx={{ flexWrap: 'wrap', gap: 0.55 }}>
                      {template.available_variables.slice(0, 4).map((variable) => (
                        <Chip
                          key={variable}
                          size="small"
                          label={`{{${variable}}}`}
                          sx={{
                            height: 20,
                            fontSize: '0.58rem',
                            bgcolor: 'rgba(0,240,255,.045)',
                            border: '1px solid rgba(0,240,255,.12)',
                            color: '#9EEAF2',
                          }}
                        />
                      ))}
                      {template.available_variables.length > 4 ? (
                        <Chip size="small" label={`+${template.available_variables.length - 4}`} sx={{ height: 20, fontSize: '0.58rem' }} />
                      ) : null}
                    </Stack>

                    <Box sx={{ flex: 1 }} />
                    <Stack direction="row" spacing={0.75} sx={{ pt: 0.5 }}>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={<Eye size={14} />}
                        onClick={() => openPreview(template)}
                        sx={{ flex: 1 }}
                      >
                        معاينة
                      </Button>
                      <Button
                        size="small"
                        variant="text"
                        startIcon={<Pencil size={13} />}
                        onClick={() => openEdit(template)}
                      >
                        تعديل
                      </Button>
                      <Button
                        size="small"
                        variant="text"
                        color="error"
                        disabled={template.is_built_in}
                        onClick={() => setPendingDelete(template)}
                        sx={{ minWidth: 36 }}
                        aria-label="حذف"
                      >
                        <Trash2 size={14} />
                      </Button>
                    </Stack>
                  </Stack>
                </Box>
              </motion.div>
            </Grid>
          ))}
        </Grid>
      )}

        </>
      )}

      {/* ------------------------------ editor ------------------------------ */}
      <Dialog
        open={editorOpen}
        onClose={() => {
          setEditorOpen(false);
          setEditing(null);
          setDesign(null);
          setTestResult(null);
        }}
        fullScreen
        PaperProps={{ sx: { bgcolor: '#070D18' } }}
      >
        <form
          onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}
          style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
        >
          <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1.5 }}>
            <FileText size={18} />
            {editing ? `تعديل القالب — ${editing.name}` : 'قالب جديد'}
            <Chip
              size="small"
              label="Visual Builder"
              sx={{
                ml: 0.5,
                height: 21,
                fontSize: '0.6rem',
                fontWeight: 900,
                color: '#00F0FF',
                bgcolor: 'rgba(0,240,255,.08)',
                border: '1px solid rgba(0,240,255,.24)',
              }}
            />
            <Box sx={{ flex: 1 }} />
            <Typography variant="caption" sx={{ color: 'text.secondary', display: { xs: 'none', md: 'block' } }}>
              حفظ التصميم يُعيد توليد HTML الآمن تلقائياً
            </Typography>
          </DialogTitle>
          <DialogContent dividers sx={{ p: { xs: 1.25, md: 2.5 }, bgcolor: '#070D18' }}>
            <Box sx={{ maxWidth: 1500, mx: 'auto' }}>
              <Box
                sx={{
                  mb: 2.5,
                  p: { xs: 1.75, sm: 2 },
                  borderRadius: 3,
                  border: '1px solid rgba(0,240,255,.22)',
                  background:
                    'radial-gradient(circle at 92% 0%, rgba(0,240,255,.13), transparent 44%), linear-gradient(145deg, rgba(20,35,58,.92), rgba(8,14,26,.9))',
                }}
              >
                <Stack direction="row" alignItems="center" spacing={0.8} sx={{ mb: 0.4 }}>
                  <Sparkles size={17} color="#00F0FF" />
                  <Typography sx={{ fontWeight: 800, fontSize: '0.92rem' }}>
                    توليد القالب بالذكاء الاصطناعي
                  </Typography>
                  <Chip
                    size="small"
                    label="AI"
                    sx={{
                      height: 20,
                      fontSize: '0.58rem',
                      fontWeight: 900,
                      color: '#00F0FF',
                      bgcolor: 'rgba(0,240,255,.1)',
                      border: '1px solid rgba(0,240,255,.28)',
                    }}
                  />
                </Stack>
                <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mb: 1.4 }}>
                  يُستخدم قطاع مؤسستك تلقائياً في الطلب. راجع الناتج قبل الحفظ؛ لن يُنشأ القالب
                  تلقائياً.
                </Typography>
                <Grid container spacing={1.5}>
                  <Grid item xs={12} sm={5}>
                    <TextField
                      size="small"
                      fullWidth
                      label="القسم المستهدف"
                      placeholder="مثال: الموارد البشرية أو المالية"
                      value={aiDepartment}
                      onChange={(event) => setAiDepartment(event.target.value)}
                      disabled={aiMutation.isPending}
                    />
                  </Grid>
                  <Grid item xs={12} sm={7}>
                    <TextField
                      size="small"
                      fullWidth
                      multiline
                      minRows={2}
                      label="السيناريو المطلوب"
                      placeholder="مثال: رسالة داخلية عاجلة عن تحديث بيانات الموظفين"
                      value={aiScenario}
                      onChange={(event) => setAiScenario(event.target.value)}
                      disabled={aiMutation.isPending}
                    />
                  </Grid>
                </Grid>
                <Stack
                  direction={{ xs: 'column', sm: 'row' }}
                  spacing={1}
                  alignItems={{ xs: 'stretch', sm: 'center' }}
                  sx={{ mt: 1.5 }}
                >
                  <Button
                    type="button"
                    variant="contained"
                    startIcon={
                      aiMutation.isPending ? (
                        <CircularProgress size={14} color="inherit" />
                      ) : undefined
                    }
                    disabled={aiMutation.isPending || !aiDepartment.trim() || !aiScenario.trim()}
                    onClick={() => {
                      setAiError(null);
                      aiMutation.mutate();
                    }}
                    sx={{
                      background: 'linear-gradient(135deg, #00F0FF 0%, #7C4DFF 100%)',
                      color: '#04101C',
                      fontWeight: 900,
                      '&:hover': {
                        background: 'linear-gradient(135deg, #5CF6FF 0%, #9B75FF 100%)',
                      },
                    }}
                  >
                    {aiMutation.isPending ? 'جارٍ توليد القالب…' : '✨ Generate with AI'}
                  </Button>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    يعبّئ الموضوع والجسم ومستوى الصعوبة تلقائياً.
                  </Typography>
                </Stack>
                {aiError ? (
                  <Alert severity="error" sx={{ mt: 1.5 }}>
                    {aiError}
                  </Alert>
                ) : null}
              </Box>

              <Grid container spacing={2} sx={{ mb: 2 }}>
                <Grid item xs={12} md={4}>
                  <TextField label="اسم القالب" required fullWidth {...form.register('name', { required: true })} />
                </Grid>
                <Grid item xs={12} md={2}>
                  <Controller
                    name="channel"
                    control={form.control}
                    render={({ field }) => (
                      <TextField
                        select
                        fullWidth
                        label="القناة"
                        value={field.value}
                        onChange={(event) => {
                          const next = event.target.value as 'email' | 'sms' | 'whatsapp';
                          field.onChange(next);
                          if (next !== 'email') {
                            const current = form.getValues('body_html');
                            const text = plainText(current);
                            if (!text || /<[a-z][\s\S]*>/i.test(current)) {
                              form.setValue('body_html', text || DEFAULT_TEXT, { shouldDirty: true });
                            }
                          } else if (!design) {
                            const initial = createDefaultDesign(branding);
                            setDesign(initial);
                            form.setValue(
                              'body_html',
                              renderEmailDesignHtml(initial, branding, { forEditor: false }),
                              { shouldDirty: true },
                            );
                          }
                        }}
                      >
                        <MenuItem value="email">بريد إلكتروني</MenuItem>
                        <MenuItem value="sms">SMS</MenuItem>
                        <MenuItem value="whatsapp">واتساب</MenuItem>
                      </TextField>
                    )}
                  />
                </Grid>
                <Grid item xs={12} md={6}>
                  <TextField
                    label={editorChannel === 'email' ? 'موضوع الرسالة' : 'العنوان الداخلي / سطر أول'}
                    required
                    fullWidth
                    {...form.register('subject', { required: true })}
                  />
                </Grid>
                <Grid item xs={12} md={7}>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    مستوى الصعوبة: {form.watch('difficulty_level')}
                  </Typography>
                  <Controller
                    name="difficulty_level"
                    control={form.control}
                    render={({ field }) => (
                      <Slider
                        value={field.value}
                        min={1}
                        max={10}
                        step={1}
                        marks={[
                          { value: 1, label: '1' },
                          { value: 5, label: '5' },
                          { value: 10, label: '10' },
                        ]}
                        onChange={(_event, value) => field.onChange(value as number)}
                      />
                    )}
                  />
                </Grid>
                <Grid item xs={12} md={5} sx={{ display: 'flex', alignItems: 'center' }}>
                  <Controller
                    name="is_active"
                    control={form.control}
                    render={({ field }) => (
                      <FormControlLabel
                        control={<Switch checked={field.value} onChange={field.onChange} />}
                        label="القالب نشط ومتاح للحملات"
                      />
                    )}
                  />
                </Grid>
              </Grid>

              {editorChannel === 'email' ? (
                design ? (
                  <EmailVisualEditor
                    design={design}
                    branding={branding}
                    onChange={setDesign}
                    subject={form.watch('subject') ?? ''}
                    onTestSend={() => {
                      setTestResult(null);
                      testSendMutation.mutate();
                    }}
                    testSending={testSendMutation.isPending}
                    testResult={testResult}
                    disabled={saveMutation.isPending}
                  />
                ) : designQuery.error ? (
                  <Alert severity="error">{errorMessage(designQuery.error)}</Alert>
                ) : (
                  <LoadingState label="جارٍ تحميل محرر التصميم…" />
                )
              ) : (
                <Grid container spacing={2}>
                  <Grid item xs={12} md={7}>
                    <Controller
                      name="body_html"
                      control={form.control}
                      render={({ field }) => (
                        <TextField
                          label="نص الرسالة (نص عادي — يُفضّل عدم تجاوز 1000 حرف)"
                          multiline
                          minRows={14}
                          fullWidth
                          value={field.value}
                          onChange={field.onChange}
                          helperText="اكتب نصاً عادياً. يُضاف رابط التتبع تلقائياً إذا لم تضعه، ويُحوَّل أي HTML إلى نص عند الإرسال."
                          inputRef={(node) => {
                            bodyRef.current = node;
                            field.ref(node);
                          }}
                          InputProps={{ sx: { direction: 'rtl', fontSize: '0.86rem' } }}
                        />
                      )}
                    />
                    {editorChannel === 'sms' ? (
                      <Stack
                        direction="row"
                        alignItems="center"
                        spacing={1}
                        sx={{ mt: 1 }}
                      >
                        <Chip
                          size="small"
                          color={smsOverLimit ? 'error' : smsLength > 140 ? 'warning' : 'success'}
                          variant={smsOverLimit ? 'filled' : 'outlined'}
                          label={`${smsLength} / ${SMS_BODY_LIMIT} حرف`}
                        />
                        <Typography
                          variant="caption"
                          sx={{ color: smsOverLimit ? 'error.main' : 'text.secondary' }}
                        >
                          {smsOverLimit
                            ? `تجاوزت الحد بـ ${smsLength - SMS_BODY_LIMIT} حرفاً — لن يُسمح بالحفظ.`
                            : 'رسالة واحدة (GSM) تشمل رابط التتبع المختصر {{link}}.'}
                        </Typography>
                      </Stack>
                    ) : null}
                  </Grid>
                  <Grid item xs={12} md={5}>
                    <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mb: 1 }}>
                      معاينة نصية
                    </Typography>
                    <Box
                      sx={{
                        border: '1px solid rgba(255,255,255,.12)',
                        borderRadius: 2,
                        bgcolor: 'rgba(3,8,18,.82)',
                        height: 360,
                        overflow: 'auto',
                        p: 2.5,
                      }}
                    >
                      <Typography
                        component="pre"
                        sx={{
                          m: 0,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          fontFamily: 'Tahoma, Arial, sans-serif',
                          fontSize: '0.88rem',
                          lineHeight: 1.9,
                          color: '#EAF6FF',
                          direction: 'rtl',
                        }}
                      >
                        {plainText(applySampleVariables(form.watch('body_html')))}
                      </Typography>
                    </Box>
                  </Grid>
                </Grid>
              )}

              {editorChannel === 'email' ? (
                <Accordion
                  disableGutters
                  sx={{
                    mt: 2,
                    bgcolor: 'rgba(255,255,255,.018)',
                    border: '1px solid rgba(255,255,255,.08)',
                    borderRadius: 2,
                    '&:before': { display: 'none' },
                  }}
                >
                  <AccordionSummary expandIcon={<ChevronDown size={17} />}>
                    <Stack direction="row" spacing={0.7} alignItems="center">
                      <Code2 size={15} color="#94A3B8" />
                      <Typography sx={{ fontSize: '0.8rem', fontWeight: 700 }}>
                        HTML المتقدم (احتياطي للمطوّرين)
                      </Typography>
                    </Stack>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mb: 1 }}>
                      تعديل HTML مباشرةً يحوّل القالب إلى وضع HTML القديم. التصميم المرئي هو
                      المصدر الافتراضي، ويُعاد توليد HTML الآمن عند الحفظ.
                    </Typography>
                    <Controller
                      name="body_html"
                      control={form.control}
                      render={({ field }) => (
                        <TextField
                          label="جسم الرسالة (HTML)"
                          multiline
                          minRows={10}
                          fullWidth
                          value={field.value}
                          onChange={(event) => {
                            field.onChange(event);
                            setDesign(legacyDesign(event.target.value, branding?.primary_color));
                          }}
                          inputRef={(node) => {
                            bodyRef.current = node;
                            field.ref(node);
                          }}
                          InputProps={{
                            sx: {
                              fontFamily: 'Consolas, monospace',
                              fontSize: '0.78rem',
                              direction: 'ltr',
                            },
                          }}
                        />
                      )}
                    />
                    <Box sx={{ mt: 1.25 }}>
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        إدراج متغيّر في موضع المؤشر
                      </Typography>
                      <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                        {VARIABLES.map((variable) => (
                          <Chip
                            key={variable}
                            size="small"
                            label={`{{${variable}}}`}
                            onClick={() => insertVariable(variable)}
                            clickable
                          />
                        ))}
                      </Stack>
                    </Box>
                  </AccordionDetails>
                </Accordion>
              ) : null}
            </Box>
          </DialogContent>
          <DialogActions sx={{ p: 2, bgcolor: '#070D18' }}>
            <Button
              onClick={() => {
                setEditorOpen(false);
                setEditing(null);
                setDesign(null);
                setTestResult(null);
              }}
            >
              إلغاء
            </Button>
            <Button
              type="submit"
              variant="contained"
              disabled={
                saveMutation.isPending ||
                smsOverLimit ||
                (editorChannel === 'email' && (!design || designQuery.isLoading))
              }
            >
              {editing ? 'حفظ التعديلات' : 'إنشاء القالب'}
            </Button>
          </DialogActions>
        </form>
      </Dialog>

      {/* ------------------------------ preview ----------------------------- */}
      <Dialog open={Boolean(previewTemplate)} onClose={() => setPreviewTemplate(null)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Mail size={18} />
          {previewTemplate?.name}
        </DialogTitle>
        <DialogContent dividers>
          <TextField
            select
            label="معاينة باسم موظف"
            fullWidth
            size="small"
            value={previewEmployeeId}
            onChange={(event) => setPreviewEmployeeId(event.target.value)}
            sx={{ mb: 2 }}
          >
            {(employeesQuery.data?.items ?? []).map((employee) => (
              <MenuItem key={employee.id} value={employee.id}>
                {employee.first_name} {employee.last_name} — {employee.email}
              </MenuItem>
            ))}
          </TextField>
          {!previewEmployeeId ? (
            <Alert severity="info">اختر موظفاً لعرض النسخة المخصصة من الرسالة.</Alert>
          ) : previewQuery.isLoading ? (
            <LoadingState label="جارٍ توليد المعاينة…" />
          ) : previewQuery.error ? (
            <Alert severity="error">{errorMessage(previewQuery.error)}</Alert>
          ) : previewQuery.data ? (
            <Box>
              <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1} sx={{ mb: 1 }}>
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  إلى: {selectedPreviewEmployee?.email}
                  {previewTemplate?.channel !== 'email' && selectedPreviewEmployee?.phone
                    ? ` · ${selectedPreviewEmployee.phone}`
                    : ''}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  الموضوع: {previewQuery.data.subject}
                </Typography>
              </Stack>
              {previewQuery.data.missing_variables.length > 0 ? (
                <Alert severity="warning" sx={{ mb: 1.5 }}>
                  متغيرات ناقصة: {previewQuery.data.missing_variables.join(', ')}
                </Alert>
              ) : null}
              {previewTemplate?.channel !== 'email' ? (
                <Box
                  sx={{
                    border: '1px solid rgba(255,255,255,.12)',
                    borderRadius: 2,
                    overflow: 'auto',
                    bgcolor: 'rgba(3,8,18,.82)',
                    maxHeight: '62vh',
                    p: 2.5,
                  }}
                >
                  <Typography
                    component="pre"
                    sx={{
                      m: 0,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      fontFamily: 'Tahoma, Arial, sans-serif',
                      fontSize: '0.92rem',
                      lineHeight: 1.9,
                      color: '#EAF6FF',
                      direction: 'rtl',
                    }}
                  >
                    {previewQuery.data.text_content ??
                      plainText(previewQuery.data.html_content)}
                  </Typography>
                </Box>
              ) : (
                <Box
                  sx={{
                    border: '1px solid rgba(255,255,255,.12)',
                    borderRadius: 2,
                    overflow: 'hidden',
                    bgcolor: '#fff',
                    height: '62vh',
                  }}
                >
                  <iframe
                    title="Personalised template preview"
                    srcDoc={previewQuery.data.html_content}
                    sandbox=""
                    style={{ width: '100%', height: '100%', border: 0 }}
                  />
                </Box>
              )}
              <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mt: 1 }}>
                {previewTemplate?.channel === 'email'
                  ? 'روابط التتبع وبكسل التتبع حيّان في هذه المعاينة.'
                  : 'هذه هي الرسالة النصية الفعلية، ويظهر رابط التتبع في نهايتها.'}
              </Typography>
            </Box>
          ) : null}
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setPreviewTemplate(null)}>إغلاق</Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="حذف القالب"
        message={`حذف «${pendingDelete?.name ?? ''}»؟ ستفقد الحملات المرتبطة به مرجع القالب.`}
        confirmLabel="حذف"
        destructive
        busy={deleteMutation.isPending}
        onConfirm={() => pendingDelete && deleteMutation.mutate(pendingDelete)}
        onClose={() => setPendingDelete(null)}
      />
    </>
  );
}
