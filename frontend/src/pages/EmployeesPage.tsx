/** Employees page: searchable table, CRUD dialogs, CSV import and timeline. */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import FormControlLabel from '@mui/material/FormControlLabel';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import Pagination from '@mui/material/Pagination';
import Stack from '@mui/material/Stack';
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
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import FileUploadIcon from '@mui/icons-material/FileUpload';
import HistoryIcon from '@mui/icons-material/History';
import PersonSearchIcon from '@mui/icons-material/PersonSearch';
import SendIcon from '@mui/icons-material/Send';
import { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Controller, useForm } from 'react-hook-form';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';

import { employeesApi } from '@/api/endpoints';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import type { Employee, EmployeeCreate } from '@/types';

const CATEGORY_COLORS: Record<string, 'default' | 'info' | 'success' | 'error'> = {
  competent: 'success',
  hesitant: 'default',
  unaware: 'info',
  critical_risk: 'error',
};

/** Human-readable labels for the engagement timeline event types. */
const TIMELINE_LABELS: Record<string, string> = {
  campaign_assigned: 'Campaign assigned',
  email_sent: 'Email accepted by the mail server',
  email_delivered: 'Email delivered',
  message_sent: 'SMS/WhatsApp accepted by the provider',
  message_delivered: 'SMS/WhatsApp delivered',
  message_read: 'SMS/WhatsApp read',
  email_opened: 'Email opened',
  link_clicked: 'Link clicked',
  training_form_viewed: 'Training form shown',
  credentials_submitted: 'Credentials entered in the simulated form',
  phishing_reported: 'Reported as phishing',
  training_completed: 'Micro-training completed',
};

/** Strict E.164: country code plus 8-15 digits, no separators. */
const E164_PATTERN = /^\+[1-9]\d{7,14}$/;

/** Colour of the timeline rail for each event type. */
function timelineColor(eventType: string): string {
  switch (eventType) {
    case 'credentials_submitted':
      return '#b42318';
    case 'phishing_reported':
      return '#0f7b3f';
    case 'link_clicked':
      return '#ed6c02';
    case 'training_completed':
      return '#0f7b3f';
    default:
      return '#c9d3de';
  }
}

interface EmployeeFormValues extends EmployeeCreate {
  is_active: boolean;
}

const EMPTY_FORM: EmployeeFormValues = {
  email: '',
  phone: '',
  first_name: '',
  last_name: '',
  department: '',
  job_title: '',
  access_level: 1,
  is_active: true,
};

export function EmployeesPage() {
  const { organizationId } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [department, setDepartment] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Employee | null>(null);
  const [timelineFor, setTimelineFor] = useState<Employee | null>(null);

  const fileInput = useRef<HTMLInputElement>(null);

  const listQuery = useQuery({
    queryKey: ['employees', organizationId, page, search, department, activeOnly],
    queryFn: () =>
      employeesApi.list(organizationId as string, {
        page,
        per_page: 20,
        search: search || undefined,
        department: department || undefined,
        is_active: activeOnly ? true : undefined,
      }),
    enabled: Boolean(organizationId),
  });

  const timelineQuery = useQuery({
    queryKey: ['timeline', organizationId, timelineFor?.id],
    queryFn: () => employeesApi.timeline(organizationId as string, timelineFor?.id as string),
    enabled: Boolean(organizationId && timelineFor),
  });

  const form = useForm<EmployeeFormValues>({ defaultValues: EMPTY_FORM });

  const saveMutation = useMutation({
    mutationFn: async (values: EmployeeFormValues) => {
      if (!organizationId) throw new Error('No organization');
      const payload: EmployeeCreate = {
        ...values,
        phone: values.phone?.trim() || null,
        department: values.department || null,
        job_title: values.job_title || null,
      };
      if (editing) {
        return employeesApi.update(organizationId, editing.id, payload);
      }
      return employeesApi.create(organizationId, payload);
    },
    onSuccess: () => {
      toast.success(editing ? 'Employee updated' : 'Employee created');
      setEditorOpen(false);
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ['employees'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: async (employee: Employee) => {
      if (!organizationId) throw new Error('No organization');
      await employeesApi.remove(organizationId, employee.id);
    },
    onSuccess: () => {
      toast.success('Employee deleted');
      setPendingDelete(null);
      void queryClient.invalidateQueries({ queryKey: ['employees'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const importMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!organizationId) throw new Error('No organization');
      return employeesApi.bulkImport(organizationId, file);
    },
    onSuccess: (result) => {
      toast.success(`Imported: ${result.created} created, ${result.updated} updated`);
      if (result.errors.length > 0) {
        toast.error(`${result.skipped} rows skipped — see server logs`);
      }
      void queryClient.invalidateQueries({ queryKey: ['employees'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const departments = useMemo(() => {
    const values = new Set<string>();
    listQuery.data?.items.forEach((employee) => {
      if (employee.department) values.add(employee.department);
    });
    return Array.from(values);
  }, [listQuery.data]);

  function openCreate() {
    setEditing(null);
    form.reset(EMPTY_FORM);
    setEditorOpen(true);
  }

  function openEdit(employee: Employee) {
    setEditing(employee);
    form.reset({
      email: employee.email,
      phone: employee.phone ?? '',
      first_name: employee.first_name,
      last_name: employee.last_name,
      department: employee.department ?? '',
      job_title: employee.job_title ?? '',
      access_level: employee.access_level,
      is_active: employee.is_active,
    });
    setEditorOpen(true);
  }

  return (
    <>
      <PageHeader
        title="Employees"
        subtitle="Company-owned addresses enrolled in authorized training simulations."
        actions={
          <Stack direction="row" spacing={1}>
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) importMutation.mutate(file);
                event.target.value = '';
              }}
            />
            <Button
              variant="outlined"
              startIcon={<FileUploadIcon />}
              onClick={() => fileInput.current?.click()}
              disabled={importMutation.isPending}
            >
              Import CSV
            </Button>
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New Employee
            </Button>
          </Stack>
        }
      />

      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="center">
            <TextField
              label="Search"
              placeholder="Name, email or department"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              size="small"
              fullWidth
            />
            <TextField
              select
              label="Department"
              value={department}
              onChange={(event) => {
                setDepartment(event.target.value);
                setPage(1);
              }}
              size="small"
              sx={{ minWidth: 200 }}
            >
              <MenuItem value="">All departments</MenuItem>
              {departments.map((value) => (
                <MenuItem key={value} value={value}>
                  {value}
                </MenuItem>
              ))}
            </TextField>
            <FormControlLabel
              control={
                <Switch
                  checked={activeOnly}
                  onChange={(event) => {
                    setActiveOnly(event.target.checked);
                    setPage(1);
                  }}
                />
              }
              label="Active only"
            />
          </Stack>
        </CardContent>
      </Card>

      {listQuery.isLoading ? (
        <LoadingState label="Loading employees…" />
      ) : listQuery.error ? (
        <Alert severity="error">{errorMessage(listQuery.error)}</Alert>
      ) : listQuery.data && listQuery.data.items.length === 0 ? (
        <Card>
          <EmptyState title="No employees found" description="Adjust your filters or add an employee." />
        </Card>
      ) : (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Email</TableCell>
                  <TableCell>Phone (E.164)</TableCell>
                  <TableCell>Department</TableCell>
                  <TableCell align="center">Access</TableCell>
                  <TableCell align="center">Score</TableCell>
                  <TableCell align="center">Category</TableCell>
                  <TableCell align="center">Clicks</TableCell>
                  <TableCell align="center">Reports</TableCell>
                  <TableCell align="center">Status</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {listQuery.data?.items.map((employee) => (
                  <TableRow key={employee.id} hover>
                    <TableCell>{`${employee.first_name} ${employee.last_name}`.trim()}</TableCell>
                    <TableCell>{employee.email}</TableCell>
                    <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                      {employee.phone?.trim() || '—'}
                    </TableCell>
                    <TableCell>{employee.department ?? '—'}</TableCell>
                    <TableCell align="center">{employee.access_level}</TableCell>
                    <TableCell align="center">{employee.immunity_score.toFixed(1)}</TableCell>
                    <TableCell align="center">
                      {employee.behavioral_category ? (
                        <Chip
                          size="small"
                          label={employee.behavioral_category}
                          color={CATEGORY_COLORS[employee.behavioral_category] ?? 'default'}
                        />
                      ) : (
                        '—'
                      )}
                    </TableCell>
                    <TableCell align="center">{employee.total_clicks}</TableCell>
                    <TableCell align="center">{employee.total_reports}</TableCell>
                    <TableCell align="center">
                      <Stack
                        direction="row"
                        spacing={0.5}
                        justifyContent="center"
                        sx={{ flexWrap: 'wrap', gap: 0.5 }}
                      >
                        <Chip
                          size="small"
                          label={employee.is_active ? 'active' : 'inactive'}
                          color={employee.is_active ? 'success' : 'default'}
                          variant="outlined"
                        />
                        {employee.is_blacklisted ? (
                          <Chip
                            size="small"
                            color="error"
                            label="BLACKLISTED: Repeated Failure"
                            sx={{ fontWeight: 800 }}
                          />
                        ) : null}
                      </Stack>
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title="Send simulation">
                        <IconButton
                          size="small"
                          aria-label="Send simulation"
                          onClick={() => navigate(`/campaigns/new?employeeId=${employee.id}`)}
                        >
                          <SendIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Full dossier">
                        <IconButton
                          size="small"
                          aria-label="Full dossier"
                          onClick={() => navigate(`/employees/${employee.id}`)}
                        >
                          <PersonSearchIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Timeline">
                        <IconButton
                          size="small"
                          aria-label="Timeline"
                          onClick={() => setTimelineFor(employee)}
                        >
                          <HistoryIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Edit">
                        <IconButton size="small" onClick={() => openEdit(employee)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton size="small" onClick={() => setPendingDelete(employee)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <Stack alignItems="center" sx={{ py: 2 }}>
            <Pagination
              count={listQuery.data?.pages ?? 1}
              page={page}
              onChange={(_event, value) => setPage(value)}
              color="primary"
            />
          </Stack>
        </Card>
      )}

      <Dialog open={editorOpen} onClose={() => setEditorOpen(false)} maxWidth="sm" fullWidth>
        <form onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}>
          <DialogTitle>{editing ? 'Edit employee' : 'New employee'}</DialogTitle>
          <DialogContent>
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField
                label="Email"
                type="email"
                required
                fullWidth
                {...form.register('email', { required: true })}
              />
              <TextField
                label="Phone (E.164)"
                placeholder="+966500000000"
                fullWidth
                {...form.register('phone', {
                  validate: (value) =>
                    !value?.trim() ||
                    E164_PATTERN.test(value.trim()) ||
                    'Use international format without spaces, e.g. +966500000000',
                })}
                error={Boolean(form.formState.errors.phone)}
                helperText={
                  form.formState.errors.phone?.message ??
                  'Required to target this employee with SMS or WhatsApp.'
                }
              />
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                <TextField label="First name" required fullWidth {...form.register('first_name', { required: true })} />
                <TextField label="Last name" fullWidth {...form.register('last_name')} />
              </Stack>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                <TextField label="Department" fullWidth {...form.register('department')} />
                <TextField label="Job title" fullWidth {...form.register('job_title')} />
              </Stack>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems="center">
                <Controller
                  name="access_level"
                  control={form.control}
                  render={({ field }) => (
                    <TextField
                      select
                      label="Access level"
                      value={field.value}
                      onChange={(event) => field.onChange(Number(event.target.value))}
                      fullWidth
                    >
                      {[1, 2, 3, 4, 5].map((level) => (
                        <MenuItem key={level} value={level}>
                          {level}
                        </MenuItem>
                      ))}
                    </TextField>
                  )}
                />
                <Controller
                  name="is_active"
                  control={form.control}
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Switch
                          checked={field.value}
                          onChange={(event) => field.onChange(event.target.checked)}
                        />
                      }
                      label="Active"
                    />
                  )}
                />
              </Stack>
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setEditorOpen(false)}>Cancel</Button>
            <Button type="submit" variant="contained" disabled={saveMutation.isPending}>
              {editing ? 'Save changes' : 'Create employee'}
            </Button>
          </DialogActions>
        </form>
      </Dialog>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete employee"
        message={`Permanently delete ${pendingDelete?.email ?? ''}? Their tracking history will be removed.`}
        confirmLabel="Delete"
        destructive
        busy={deleteMutation.isPending}
        onConfirm={() => pendingDelete && deleteMutation.mutate(pendingDelete)}
        onClose={() => setPendingDelete(null)}
      />

      <Dialog
        open={Boolean(timelineFor)}
        onClose={() => setTimelineFor(null)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Timeline — {timelineFor?.email}</DialogTitle>
        <DialogContent dividers>
          {timelineQuery.isLoading ? (
            <LoadingState label="Loading timeline…" />
          ) : timelineQuery.error ? (
            <Alert severity="error">{errorMessage(timelineQuery.error)}</Alert>
          ) : (timelineQuery.data ?? []).length === 0 ? (
            <Typography color="text.secondary">No activity recorded yet.</Typography>
          ) : (
            <Stack spacing={1.25}>
              {(timelineQuery.data ?? []).map((event, index, all) => (
                <Box key={`${event.event_type}-${index}`} sx={{ display: 'flex', gap: 1.25 }}>
                  <Box
                    sx={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      pt: 0.6,
                      width: 14,
                      flex: '0 0 auto',
                    }}
                  >
                    <Box
                      sx={{
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        flex: '0 0 auto',
                        bgcolor: timelineColor(event.event_type),
                        boxShadow: `0 0 0 3px ${timelineColor(event.event_type)}22, 0 0 12px ${timelineColor(event.event_type)}66`,
                      }}
                    />
                    {index < all.length - 1 ? (
                      <Box
                        sx={{
                          width: 2,
                          flex: 1,
                          minHeight: 12,
                          my: 0.5,
                          borderRadius: 1,
                          background: `linear-gradient(180deg, ${timelineColor(event.event_type)}66, rgba(255,255,255,.05))`,
                        }}
                      />
                    ) : null}
                  </Box>
                  <Box
                    sx={{
                      flex: 1,
                      minWidth: 0,
                      px: 1.5,
                      py: 1,
                      borderRadius: 2.5,
                      border: '1px solid rgba(255,255,255,.06)',
                      background:
                        'linear-gradient(135deg, rgba(255,255,255,.035), rgba(255,255,255,.008))',
                      transition: 'border-color .2s ease, transform .2s ease',
                      '&:hover': {
                        borderColor: `${timelineColor(event.event_type)}66`,
                        transform: 'translateX(-2px)',
                      },
                    }}
                  >
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, lineHeight: 1.5 }}>
                    {TIMELINE_LABELS[event.event_type] ?? event.event_type.replace(/_/g, ' ')}
                    {event.campaign_name ? ` — ${event.campaign_name}` : ''}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {formatDateTime(event.timestamp)}
                  </Typography>
                  {event.event_type === 'credentials_submitted' && event.details ? (
                    <Box sx={{ mt: 0.5 }}>
                      <Typography variant="body2">
                        Identifier typed:{' '}
                        <Box component="span" sx={{ fontFamily: 'monospace' }}>
                          {String(event.details.identifier ?? '—')}
                        </Box>
                      </Typography>
                      {Object.entries(
                        (event.details.values as Record<string, string> | undefined) ?? {},
                      ).map(([key, value]) => (
                        <Typography key={key} variant="body2">
                          {key}:{' '}
                          <Box component="span" sx={{ fontFamily: 'monospace' }}>
                            {key.toLowerCase().includes('pass') ? '••••••' : value}
                          </Box>
                        </Typography>
                      ))}
                      {event.details.password_length !== undefined ? (
                        <Typography variant="body2" color="text.secondary">
                          Password length recorded: {String(event.details.password_length)} — open
                          the full dossier to reveal the captured value.
                        </Typography>
                      ) : null}
                    </Box>
                  ) : null}
                  </Box>
                </Box>
              ))}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            component={RouterLink}
            to={`/employees/${timelineFor?.id ?? ''}`}
            startIcon={<PersonSearchIcon />}
            onClick={() => setTimelineFor(null)}
          >
            Full dossier
          </Button>
          <Button onClick={() => setTimelineFor(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
