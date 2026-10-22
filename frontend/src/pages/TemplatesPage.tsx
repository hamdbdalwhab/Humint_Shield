/**
 * Email template gallery — Arabic-first, Midnight Cyber edition.
 *
 * The page is a real catalogue, not a mock: every card is backed by the
 * organization's template records, thumbnails render the actual inline-CSS
 * email inside a sandboxed iframe, and the preview dialog renders the
 * personalised email produced by the backend for a real employee.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
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
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { alpha } from '@mui/material/styles';
import { motion } from 'framer-motion';
import {
  Code2,
  Eye,
  FileText,
  Layers,
  Mail,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Wand2,
} from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';

import { employeesApi, templatesApi } from '@/api/endpoints';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import type { EmailTemplate, EmailTemplateCreate } from '@/types';

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

interface TemplateFormValues {
  name: string;
  subject: string;
  body_html: string;
  difficulty_level: number;
  is_active: boolean;
}

const EMPTY_TEMPLATE: TemplateFormValues = {
  name: '',
  subject: '',
  body_html: DEFAULT_BODY,
  difficulty_level: 5,
  is_active: true,
};

function previewDocument(html: string): string {
  if (/<html[\s>]/i.test(html)) return html;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" /></head><body style="margin:0;background:#f2f4f7;font-family:Arial,sans-serif">${html}</body></html>`;
}

function localPreview(html: string): string {
  return previewDocument(
    html
      .replace(/\{\{first_name\}\}/g, 'Jane')
      .replace(/\{\{last_name\}\}/g, 'Doe')
      .replace(/\{\{email\}\}/g, 'jane.doe@company.com')
      .replace(/\{\{company_name\}\}/g, 'Acme Corporation')
      .replace(/\{\{department\}\}/g, 'Finance')
      .replace(/\{\{manager_name\}\}/g, 'Omar Hassan')
      .replace(/\{\{invoice_number\}\}/g, 'INV-2026-8841')
      .replace(/\{\{meeting_time\}\}/g, 'Thursday, 10:30 AM')
      .replace(/\{\{tracking_url\}\}/g, '#'),
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
  const { organizationId } = useAuth();
  const queryClient = useQueryClient();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<EmailTemplate | null>(null);
  const [previewTemplate, setPreviewTemplate] = useState<EmailTemplate | null>(null);
  const [previewEmployeeId, setPreviewEmployeeId] = useState('');
  const [pendingDelete, setPendingDelete] = useState<EmailTemplate | null>(null);
  const [search, setSearch] = useState('');
  const [difficulty, setDifficulty] = useState('all');
  const bodyRef = useRef<HTMLTextAreaElement | null>(null);
  const form = useForm<TemplateFormValues>({ defaultValues: EMPTY_TEMPLATE });

  const templatesQuery = useQuery({
    queryKey: ['templates', organizationId],
    queryFn: () => templatesApi.list(organizationId as string),
    enabled: Boolean(organizationId),
  });

  const employeesQuery = useQuery({
    queryKey: ['employees', organizationId, 'preview-picker'],
    queryFn: () => employeesApi.list(organizationId as string, { per_page: 200 }),
    enabled: Boolean(organizationId),
  });

  const saveMutation = useMutation({
    mutationFn: async (values: TemplateFormValues) => {
      if (!organizationId) throw new Error('No organization');
      if (editing) return templatesApi.update(organizationId, editing.id, values);
      return templatesApi.create(organizationId, values as EmailTemplateCreate);
    },
    onSuccess: () => {
      toast.success(editing ? 'تم تحديث القالب' : 'تم إنشاء القالب');
      setEditorOpen(false);
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ['templates'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

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
      return matchesSearch && matchesDifficulty;
    });
  }, [templates, search, difficulty]);

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
    form.reset(EMPTY_TEMPLATE);
    setEditorOpen(true);
  }

  function openEdit(template: EmailTemplate) {
    setEditing(template);
    form.reset({
      name: template.name,
      subject: template.subject,
      body_html: template.body_html,
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
                      <Chip
                        size="small"
                        label={`L${template.difficulty_level}`}
                        color={template.difficulty_level >= 4 ? 'error' : template.difficulty_level >= 3 ? 'warning' : 'success'}
                        variant="outlined"
                        sx={{ fontSize: '0.62rem', fontWeight: 800, flex: '0 0 auto' }}
                      />
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

      {/* ------------------------------ editor ------------------------------ */}
      <Dialog open={editorOpen} onClose={() => setEditorOpen(false)} maxWidth="lg" fullWidth>
        <form onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}>
          <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <FileText size={18} />
            {editing ? `تعديل القالب — ${editing.name}` : 'قالب جديد'}
          </DialogTitle>
          <DialogContent dividers>
            <Grid container spacing={2.5} sx={{ mt: 0 }}>
              <Grid item xs={12} md={7}>
                <Stack spacing={2}>
                  <TextField label="اسم القالب" required fullWidth {...form.register('name', { required: true })} />
                  <TextField label="موضوع الرسالة" required fullWidth {...form.register('subject', { required: true })} />
                  <TextField
                    label="جسم الرسالة (HTML)"
                    multiline
                    minRows={12}
                    fullWidth
                    inputRef={(node) => {
                      bodyRef.current = node;
                      form.register('body_html', { required: true }).ref(node);
                    }}
                    InputProps={{ sx: { fontFamily: 'Consolas, monospace', fontSize: '0.78rem', direction: 'ltr' } }}
                  />
                  <Box>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      إدراج متغيّر
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
                  <Box>
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
                          max={5}
                          step={1}
                          marks
                          onChange={(_event, value) => field.onChange(value as number)}
                        />
                      )}
                    />
                  </Box>
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
                </Stack>
              </Grid>
              <Grid item xs={12} md={5}>
                <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: 1 }}>
                  <Eye size={15} color="#00F0FF" />
                  <Typography sx={{ fontWeight: 800, fontSize: '0.9rem' }}>معاينة مباشرة</Typography>
                </Stack>
                <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mb: 1 }}>
                  البيانات المعروضة تجريبية. استخدم «معاينة» لرؤية القالب ببيانات موظف حقيقي.
                </Typography>
                <Box
                  sx={{
                    border: '1px solid rgba(255,255,255,.10)',
                    borderRadius: 2,
                    overflow: 'hidden',
                    bgcolor: '#fff',
                    height: 430,
                  }}
                >
                  <iframe
                    title="Live template preview"
                    srcDoc={localPreview(form.watch('body_html'))}
                    sandbox=""
                    style={{ width: '100%', height: '100%', border: 0 }}
                  />
                </Box>
              </Grid>
            </Grid>
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setEditorOpen(false)}>إلغاء</Button>
            <Button type="submit" variant="contained" disabled={saveMutation.isPending}>
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
              <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mt: 1 }}>
                روابط التتبع وبكسل التتبع حيّان في هذه المعاينة.
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
