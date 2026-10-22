/**
 * New campaign wizard: Details → Targets → Review → Launch.
 *
 * Each step is self-contained and validates before advancing:
 *
 * 1. **Details** — name, template (with a sandboxed visual preview) and
 *    difficulty.
 * 2. **Targets** — filterable audience with per-department counts, bulk
 *    selection of everything that matches the current filters, and a removable
 *    selection summary. Chosen employees are kept in a map so the review step can
 *    list them even after the filters change.
 * 3. **Review** — the exact campaign, the exact recipients and an explicit
 *    "this sends real email" confirmation before anything leaves the server.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import FormControlLabel from '@mui/material/FormControlLabel';
import LinearProgress from '@mui/material/LinearProgress';
import Link from '@mui/material/Link';
import MenuItem from '@mui/material/MenuItem';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import Step from '@mui/material/Step';
import StepLabel from '@mui/material/StepLabel';
import Stepper from '@mui/material/Stepper';
import Switch from '@mui/material/Switch';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CloseIcon from '@mui/icons-material/Close';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';

import { campaignsApi, diagnosticsApi, employeesApi, templatesApi } from '@/api/endpoints';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import type { Employee } from '@/types';

const STEPS = ['التفاصيل', 'المستهدفون', 'المراجعة'];

function difficultyLabel(value: number): string {
  if (value <= 3) return 'سهل — مؤشرات واضحة';
  if (value <= 6) return 'متوسط — واقعي لكن قابل للكشف';
  return 'صعب — خفيّ ومستعجل';
}

export function NewCampaignPage() {
  const { organizationId } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const preselectId = searchParams.get('employeeId');

  const [step, setStep] = useState(0);
  const [name, setName] = useState('');
  const [templateId, setTemplateId] = useState('');
  const [difficulty, setDifficulty] = useState(5);
  const [selected, setSelected] = useState<Map<string, Employee>>(new Map());
  const [search, setSearch] = useState('');
  const [department, setDepartment] = useState('');
  const [activeOnly, setActiveOnly] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  // A failed launch (e.g. Brevo temporarily blocking the server IP) leaves the
  // campaign as a draft. Reuse it on retry so the operator never accumulates
  // orphan drafts or sends twice.
  const draftIdRef = useRef<string | null>(null);
  const quickSendRef = useRef(false);
  const [launchError, setLaunchError] = useState<string | null>(null);

  const templatesQuery = useQuery({
    queryKey: ['templates', organizationId],
    queryFn: () => templatesApi.list(organizationId as string, { is_active: true }),
    enabled: Boolean(organizationId),
  });

  const employeesQuery = useQuery({
    queryKey: ['employees', organizationId, 'wizard', search, department, activeOnly],
    queryFn: () =>
      employeesApi.list(organizationId as string, {
        per_page: 200,
        search: search || undefined,
        department: department || undefined,
        is_active: activeOnly ? true : undefined,
      }),
    enabled: Boolean(organizationId),
  });

  // Opening the wizard from an employee dossier carries `?employeeId=…` so the
  // person the operator just selected is already a target. This matches the
  // expected "select an employee → send a simulation" flow and removes a step
  // where the selection could silently be lost.
  const preselectQuery = useQuery({
    queryKey: ['employee', organizationId, preselectId],
    queryFn: () => employeesApi.get(organizationId as string, preselectId as string),
    enabled: Boolean(organizationId && preselectId),
  });

  useEffect(() => {
    const employee = preselectQuery.data;
    if (!employee) return;
    setName((current) => current || `توعية أمنية · ${employee.first_name || employee.email}`);
    setSelected((current) => {
      if (current.has(employee.id)) return current;
      const next = new Map(current);
      next.set(employee.id, employee);
      return next;
    });
  }, [preselectQuery.data]);

  // A dossier "Send simulation" link is a quick-send flow: pick the default
  // template and go straight to review. Without this the operator lands on an
  // empty first step and can mistake the preselection for a completed send.
  useEffect(() => {
    if (!preselectId || templateId) return;
    const firstTemplate = templatesQuery.data?.[0];
    if (firstTemplate) setTemplateId(firstTemplate.id);
  }, [preselectId, templateId, templatesQuery.data]);

  useEffect(() => {
    if (!preselectId || quickSendRef.current) return;
    if (!name || !templateId || !preselectQuery.data) return;
    quickSendRef.current = true;
    setStep(2);
  }, [preselectId, name, templateId, preselectQuery.data]);

  // Verify the outbound path before showing "Launch". A blocked Brevo IP is
  // the most common cause of a launch that produces no email; surfacing it on
  // the review step prevents an operator from assuming the send succeeded.
  const preflightQuery = useQuery({
    queryKey: ['delivery-preflight'],
    queryFn: () => diagnosticsApi.verifyBrevo(),
    enabled: step === 2,
    staleTime: 15_000,
    retry: false,
  });

  const launchMutation = useMutation({
    mutationFn: async () => {
      if (!organizationId) throw new Error('No organization');
      const targets = Array.from(selected.keys());
      let campaignId = draftIdRef.current;
      if (!campaignId) {
        const campaign = await campaignsApi.create(organizationId, {
          name,
          template_id: templateId,
          difficulty_level: difficulty,
          target_employee_ids: targets,
        });
        campaignId = campaign.id;
        draftIdRef.current = campaign.id;
      } else {
        // Keep the retried draft in sync with the review step.
        await campaignsApi.update(organizationId, campaignId, {
          name,
          template_id: templateId,
          target_employee_ids: targets,
        });
      }
      return campaignsApi.launch(organizationId, campaignId);
    },
    onSuccess: (result) => {
      setConfirmOpen(false);
      setLaunchError(null);
      if (result.failed > 0) {
        toast.error(`أُرسل ${result.sent} من ${result.total}؛ فشل ${result.failed}.`);
      } else {
        toast.success(`أُرسل ${result.sent} من ${result.total} رسالة. المراقبة الحية جاهزة.`);
      }
      navigate(`/campaigns/${result.campaign_id}/live`);
    },
    onError: (error) => {
      setConfirmOpen(false);
      const message = errorMessage(error);
      setLaunchError(message);
      toast.error(message);
    },
  });

  const visibleEmployees = useMemo(
    () => employeesQuery.data?.items ?? [],
    [employeesQuery.data],
  );

  const departments = useMemo(() => {
    const counts = new Map<string, number>();
    visibleEmployees.forEach((employee) => {
      if (!employee.department) return;
      counts.set(employee.department, (counts.get(employee.department) ?? 0) + 1);
    });
    return Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [visibleEmployees]);

  const selectedTemplate = templatesQuery.data?.find((template) => template.id === templateId);
  const allVisibleSelected =
    visibleEmployees.length > 0 && visibleEmployees.every((employee) => selected.has(employee.id));

  function toggleEmployee(employee: Employee) {
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(employee.id)) next.delete(employee.id);
      else next.set(employee.id, employee);
      return next;
    });
  }

  function selectAllVisible() {
    setSelected((current) => {
      const next = new Map(current);
      visibleEmployees.forEach((employee) => next.set(employee.id, employee));
      return next;
    });
  }

  function clearAll() {
    setSelected(new Map());
  }

  function removeSelected(id: string) {
    setSelected((current) => {
      const next = new Map(current);
      next.delete(id);
      return next;
    });
  }

  const canLeaveStepOne = name.trim().length > 0 && templateId.length > 0;
  const canLeaveStepTwo = selected.size > 0;
  const selectedList = Array.from(selected.values());

  return (
    <>
      <PageHeader
        title="حملة جديدة"
        subtitle="ثلاث خطوات: التفاصيل، تحديد المستهدفين، ثم مراجعة الإطلاق."
      />

      <Box
        sx={{
          mb: 3,
          p: { xs: 1.5, sm: 2 },
          borderRadius: 4,
          border: '1px solid rgba(0,240,255,.14)',
          background:
            'radial-gradient(circle at 50% 0%, rgba(0,240,255,.10), transparent 55%), linear-gradient(145deg, rgba(21,32,52,.82), rgba(9,15,26,.86))',
          boxShadow: '0 18px 50px rgba(0,0,0,.25)',
        }}
      >
        <Stepper
          alternativeLabel
          activeStep={step}
          sx={{
            '& .MuiStepLabel-label': { fontWeight: 700, mt: 0.5 },
            '& .MuiStepIcon-root': { color: 'rgba(255,255,255,.10)' },
            '& .MuiStepIcon-root.Mui-active': {
              color: 'primary.main',
              filter: 'drop-shadow(0 0 10px rgba(0,240,255,.85))',
            },
            '& .MuiStepIcon-root.Mui-completed': {
              color: 'success.main',
              filter: 'drop-shadow(0 0 8px rgba(0,230,118,.55))',
            },
            '& .MuiStepConnector-line': { borderColor: 'rgba(255,255,255,.12)' },
          }}
        >
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>
      </Box>

      {step === 0 ? (
        <Card>
          <CardContent>
            <Stack spacing={3}>
              <TextField
                label="اسم الحملة"
                required
                fullWidth
                value={name}
                onChange={(event) => setName(event.target.value)}
                helperText="اسم داخلي — لا يظهر للمستهدفين أبداً."
              />
              <TextField select label="قناة الإرسال" value="email" fullWidth disabled>
                <MenuItem value="email">البريد الإلكتروني</MenuItem>
              </TextField>
              <TextField
                select
                label="القالب"
                required
                fullWidth
                value={templateId}
                onChange={(event) => {
                  const nextId = event.target.value as string;
                  setTemplateId(nextId);
                  const template = templatesQuery.data?.find((item) => item.id === nextId);
                  if (template) setDifficulty(template.difficulty_level);
                }}
                disabled={templatesQuery.isLoading}
                helperText={
                  templatesQuery.data && templatesQuery.data.length === 0
                    ? 'لا توجد قوالب نشطة — أنشئ قالباً من صفحة القوالب أولاً.'
                    : 'القالب يحدد قصة المرسل والموضوع ونص الرسالة.'
                }
              >
                {(templatesQuery.data ?? []).map((template) => (
                  <MenuItem key={template.id} value={template.id}>
                    {template.name} (L{template.difficulty_level})
                  </MenuItem>
                ))}
              </TextField>

              {selectedTemplate ? (
                <Card variant="outlined">
                  <CardContent>
                    <Stack
                      direction={{ xs: 'column', sm: 'row' }}
                      justifyContent="space-between"
                      alignItems={{ xs: 'flex-start', sm: 'center' }}
                      spacing={1}
                      sx={{ mb: 1 }}
                    >
                      <Box>
                        <Typography variant="subtitle2">معاينة القالب</Typography>
                        <Typography variant="body2" color="text.secondary">
                          الموضوع: {selectedTemplate.subject}
                        </Typography>
                      </Box>
                      <Stack direction="row" spacing={1}>
                        <Chip size="small" label={`الصعوبة ${selectedTemplate.difficulty_level}`} />
                        {selectedTemplate.is_built_in ? (
                          <Chip size="small" variant="outlined" label="أساسي" />
                        ) : null}
                      </Stack>
                    </Stack>
                    <Box
                      component="iframe"
                      title="Template preview"
                      sandbox=""
                      srcDoc={selectedTemplate.body_html}
                      sx={{
                        width: '100%',
                        height: 300,
                        border: '1px solid',
                        borderColor: 'divider',
                        borderRadius: 1,
                        bgcolor: '#ffffff',
                      }}
                    />
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                      المتغيرات المستخدمة:{' '}
                      {selectedTemplate.available_variables.length > 0
                        ? selectedTemplate.available_variables.join(', ')
                        : 'لا يوجد'}
                    </Typography>
                  </CardContent>
                </Card>
              ) : null}

              <Box>
                <Typography variant="body2" gutterBottom>
                  مستوى الصعوبة: {difficulty} — {difficultyLabel(difficulty)}
                </Typography>
                <Slider
                  value={difficulty}
                  min={1}
                  max={10}
                  step={1}
                  marks
                  onChange={(_event, value) => setDifficulty(value as number)}
                />
              </Box>
              <Stack direction="row" justifyContent="flex-end">
                <Button variant="contained" disabled={!canLeaveStepOne} onClick={() => setStep(1)}>
                  متابعة إلى المستهدفين
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {step === 1 ? (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="center">
                <TextField
                  label="بحث بالاسم أو البريد"
                  size="small"
                  fullWidth
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                <TextField
                  select
                  label="القسم"
                  size="small"
                  sx={{ minWidth: 220 }}
                  value={department}
                  onChange={(event) => setDepartment(event.target.value)}
                >
                  <MenuItem value="">كل الأقسام</MenuItem>
                  {departments.map(([value, count]) => (
                    <MenuItem key={value} value={value}>
                      {value} ({count})
                    </MenuItem>
                  ))}
                </TextField>
                <FormControlLabel
                  control={
                    <Switch
                      checked={activeOnly}
                      onChange={(event) => setActiveOnly(event.target.checked)}
                    />
                  }
                  label="الحسابات النشطة فقط"
                />
              </Stack>

              <Stack
                direction={{ xs: 'column', sm: 'row' }}
                spacing={1}
                alignItems={{ xs: 'stretch', sm: 'center' }}
              >
                <Button size="small" variant="outlined" onClick={selectAllVisible} disabled={visibleEmployees.length === 0}>
                  {allVisibleSelected ? 'كل النتائج محددة مسبقاً' : `تحديد كل النتائج (${visibleEmployees.length})`}
                </Button>
                <Button size="small" onClick={clearAll} disabled={selected.size === 0}>
                  مسح الكل
                </Button>
                <Box sx={{ flex: 1 }} />
                <Chip color="primary" label={`${selected.size} موظفاً محدداً`} />
              </Stack>

              {selected.size > 0 ? (
                <Box
                  sx={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 1,
                    p: 1.5,
                    borderRadius: 1,
                    bgcolor: 'action.hover',
                  }}
                >
                  {selectedList.slice(0, 40).map((employee) => (
                    <Chip
                      key={employee.id}
                      size="small"
                      label={`${employee.first_name} ${employee.last_name}`.trim() || employee.email}
                      onDelete={() => removeSelected(employee.id)}
                      deleteIcon={<CloseIcon />}
                    />
                  ))}
                  {selected.size > 40 ? (
                    <Chip size="small" variant="outlined" label={`+${selected.size - 40} آخرون`} />
                  ) : null}
                </Box>
              ) : null}

              {employeesQuery.isLoading ? (
                <LoadingState label="جارٍ تحميل الموظفين…" />
              ) : (
                <TableContainer sx={{ maxHeight: 440 }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell padding="checkbox">تحديد</TableCell>
                        <TableCell>الاسم</TableCell>
                        <TableCell>البريد</TableCell>
                        <TableCell>القسم</TableCell>
                        <TableCell align="center">مستوى الوصول</TableCell>
                        <TableCell>آخر اختبار</TableCell>
                        <TableCell align="center">المناعة</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {visibleEmployees.map((employee) => (
                        <TableRow
                          key={employee.id}
                          hover
                          onClick={() => toggleEmployee(employee)}
                          sx={{ cursor: 'pointer' }}
                          selected={selected.has(employee.id)}
                        >
                          <TableCell padding="checkbox">
                            <Checkbox
                              checked={selected.has(employee.id)}
                              onClick={(event) => event.stopPropagation()}
                              onChange={() => toggleEmployee(employee)}
                            />
                          </TableCell>
                          <TableCell>
                            {employee.first_name} {employee.last_name}
                          </TableCell>
                          <TableCell>{employee.email}</TableCell>
                          <TableCell>{employee.department ?? '—'}</TableCell>
                          <TableCell align="center">{employee.access_level}</TableCell>
                          <TableCell>
                            {employee.last_test_date
                              ? formatDateTime(employee.last_test_date)
                              : 'لم يُختبر'}
                          </TableCell>
                          <TableCell align="center">{employee.immunity_score.toFixed(1)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}

              <Box
                sx={{
                  position: 'sticky',
                  bottom: 16,
                  zIndex: 3,
                  mt: 1,
                  p: 1.5,
                  borderRadius: 3,
                  border: '1px solid rgba(0,240,255,.22)',
                  background: 'linear-gradient(135deg, rgba(19,29,48,.96), rgba(10,16,28,.96))',
                  backdropFilter: 'blur(18px)',
                  boxShadow: '0 24px 60px rgba(0,0,0,.55), 0 0 32px rgba(0,240,255,.08)',
                }}
              >
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', sm: 'center' }}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Box
                      sx={{
                        width: 34,
                        height: 34,
                        borderRadius: 2,
                        display: 'grid',
                        placeItems: 'center',
                        color: 'primary.main',
                        bgcolor: 'rgba(0,240,255,.08)',
                        border: '1px solid rgba(0,240,255,.22)',
                        fontWeight: 800,
                        fontSize: '0.8rem',
                      }}
                    >
                      {selected.size}
                    </Box>
                    <Box>
                      <Typography sx={{ fontWeight: 700, fontSize: '0.82rem', lineHeight: 1.4 }}>
                        {selected.size === 0 ? 'لم يتم اختيار موظفين بعد' : `${selected.size} موظفاً محدداً`}
                      </Typography>
                      <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.66rem' }}>
                        سيُرسل لكل موظف رابط تتبع فريد
                      </Typography>
                    </Box>
                  </Stack>
                  <Box sx={{ flex: 1 }} />
                  <Stack direction="row" spacing={1}>
                    <Button onClick={() => setStep(0)}>رجوع</Button>
                    <Button
                      variant="contained"
                      disabled={!canLeaveStepTwo}
                      onClick={() => setStep(2)}
                    >
                      متابعة إلى المراجعة
                    </Button>
                  </Stack>
                </Stack>
              </Box>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {step === 2 ? (
        <Card>
          <CardContent>
            <Stack spacing={3}>
              <Box>
                <Typography variant="h3" sx={{ fontSize: '1.05rem' }} gutterBottom>
                  ملخص الحملة
                </Typography>
                <Stack spacing={1}>
                  <Typography variant="body2">
                    <strong>الاسم:</strong> {name}
                  </Typography>
                  <Typography variant="body2">
                    <strong>القناة:</strong> البريد الإلكتروني
                  </Typography>
                  <Typography variant="body2">
                    <strong>القالب:</strong> {selectedTemplate?.name ?? '—'}
                  </Typography>
                  <Typography variant="body2">
                    <strong>الموضوع:</strong> {selectedTemplate?.subject ?? '—'}
                  </Typography>
                  <Typography variant="body2">
                    <strong>الصعوبة:</strong> {difficulty} — {difficultyLabel(difficulty)}
                  </Typography>
                  <Typography variant="body2">
                    <strong>المستهدفون:</strong> {selected.size} موظفاً
                  </Typography>
                </Stack>
              </Box>

              <Divider />

              <Box>
                <Typography variant="h3" sx={{ fontSize: '1.05rem' }} gutterBottom>
                  المستهدفون ({selectedList.length})
                </Typography>
                <TableContainer sx={{ maxHeight: 320 }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>الاسم</TableCell>
                        <TableCell>البريد</TableCell>
                        <TableCell>القسم</TableCell>
                        <TableCell>المسمى الوظيفي</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {selectedList.map((employee) => (
                        <TableRow key={employee.id}>
                          <TableCell>
                            {employee.first_name} {employee.last_name}
                          </TableCell>
                          <TableCell>{employee.email}</TableCell>
                          <TableCell>{employee.department ?? '—'}</TableCell>
                          <TableCell>{employee.job_title ?? '—'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Box>

              {preflightQuery.isFetching ? (
                <Alert severity="info">جارٍ التحقق من جاهزية الإرسال الحقيقي…</Alert>
              ) : preflightQuery.data && !preflightQuery.data.valid ? (
                <Alert
                  severity="error"
                  action={
                    <Button color="inherit" size="small" onClick={() => preflightQuery.refetch()}>
                      إعادة التحقق
                    </Button>
                  }
                >
                  <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                    الإرسال الحقيقي محجوب — الإطلاق لن يُرسل أي رسالة.
                  </Typography>
                  <Typography variant="body2">
                    {preflightQuery.data.hint ?? preflightQuery.data.error ?? 'فشل فحص الإرسال.'}
                  </Typography>
                  {preflightQuery.data.blocked_ip ? (
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', mt: 0.5 }}>
                      عنوان IP المحجوب: {preflightQuery.data.blocked_ip}
                    </Typography>
                  ) : null}
                  {preflightQuery.data.action_url ? (
                    <Link
                      href={preflightQuery.data.action_url}
                      target="_blank"
                      rel="noreferrer"
                      underline="hover"
                      sx={{ display: 'inline-block', mt: 0.5 }}
                    >
                      فتح إعدادات مزوّد البريد
                    </Link>
                  ) : null}
                </Alert>
              ) : preflightQuery.data?.valid ? (
                <Alert severity="success">
                  الإرسال جاهز — {preflightQuery.data.detail?.transport === 'smtp' ? 'SMTP' : 'Brevo'}{' '}
                  استلم إعدادات المرسل بنجاح.
                </Alert>
              ) : preflightQuery.error ? (
                <Alert severity="warning">
                  تعذّر التحقق من الإرسال الآن: {errorMessage(preflightQuery.error)}. يمكنك المحاولة،
                  وستظهر النتيجة أدناه.
                </Alert>
              ) : null}

              {launchError ? (
                <Alert
                  severity="error"
                  action={
                    <Button color="inherit" size="small" onClick={() => launchMutation.mutate()}>
                      إعادة المحاولة
                    </Button>
                  }
                >
                  <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                    حُفظت الحملة كمسودة، لكن لم تُرسل أي رسالة.
                  </Typography>
                  <Typography variant="body2">{launchError}</Typography>
                </Alert>
              ) : null}

              <Alert severity="warning">
                سيتم إرسال <strong>{selected.size} رسالة حقيقية</strong> من عنوان المرسل المُعدّ.
                يجب أن تكون العناوين مملوكة للشركة ومشمولة بسياسة الاستخدام المقبول. كل فتح ونقرة
                وقيمة مُدخلة تُسجّل في تقرير الحملة.
              </Alert>

              <Stack direction="row" justifyContent="space-between">
                <Button onClick={() => setStep(1)}>رجوع</Button>
                <Tooltip title={selected.size === 0 ? 'اختر مستهدفاً واحداً على الأقل' : ''}>
                  <span>
                    <Button
                      variant="contained"
                      color="warning"
                      startIcon={
                        launchMutation.isPending ? (
                          <CircularProgress size={18} color="inherit" />
                        ) : null
                      }
                      disabled={launchMutation.isPending || selected.size === 0}
                      onClick={() => setConfirmOpen(true)}
                    >
                      إطلاق الحملة
                    </Button>
                  </span>
                </Tooltip>
              </Stack>

              {launchMutation.isPending ? (
                <Box>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    جارٍ إرسال {selected.size} رسالة…
                  </Typography>
                  <LinearProgress />
                </Box>
              ) : null}
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        title="تأكيد الإطلاق"
        message={`سيتم إرسال ${selected.size} رسالة حقيقية إلى الموظفين المحددين. هل تريد المتابعة؟`}
        confirmLabel="إرسال الرسائل"
        destructive
        busy={launchMutation.isPending}
        onConfirm={() => launchMutation.mutate()}
        onClose={() => setConfirmOpen(false)}
      />
    </>
  );
}
