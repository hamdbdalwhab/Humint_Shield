/**
 * Assignments: remediation tracking for training modules.
 *
 * An assignment is an internal training task, never an email. The page now
 * derives an "overdue" state from the due date (the database only stores
 * ``assigned``/``completed``) so a past-due remediation cannot masquerade as
 * healthy, and all write actions are gated by ``lms.manage``.
 */
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import AddIcon from '@mui/icons-material/Add';
import SearchIcon from '@mui/icons-material/Search';
import SendIcon from '@mui/icons-material/Send';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';

import { employeesApi, lmsApi } from '@/api/endpoints';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { StatCard } from '@/components/StatCard';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDate } from '@/lib/format';
import type { Assignment } from '@/types';

const STATUS_OPTIONS = ['all', 'assigned', 'completed', 'overdue'] as const;

const STATUS_COLORS: Record<string, 'default' | 'info' | 'success' | 'warning'> = {
  assigned: 'info',
  completed: 'success',
  overdue: 'warning',
};

/** An assignment is overdue when it is open and its due date has passed. */
function isOverdue(assignment: Assignment): boolean {
  if (assignment.status === 'completed' || !assignment.due_date) return false;
  return new Date(assignment.due_date).getTime() < Date.now();
}

function derivedStatus(assignment: Assignment): string {
  return isOverdue(assignment) ? 'overdue' : assignment.status;
}

export function AssignmentsPage() {
  const { organizationId, can } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const canManage = can('lms.manage');

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [moduleId, setModuleId] = useState('');
  const [employeeId, setEmployeeId] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [notes, setNotes] = useState('');

  const assignmentsQuery = useQuery({
    queryKey: ['assignments', organizationId],
    queryFn: () => lmsApi.assignments(organizationId as string),
    enabled: Boolean(organizationId),
  });

  const modulesQuery = useQuery({
    queryKey: ['modules', organizationId],
    queryFn: () => lmsApi.modules(organizationId as string),
    enabled: Boolean(organizationId && dialogOpen),
  });

  const employeesQuery = useQuery({
    queryKey: ['employees', organizationId, 'assignment-picker'],
    queryFn: () => employeesApi.list(organizationId as string, { per_page: 200, is_active: true }),
    enabled: Boolean(organizationId && dialogOpen),
  });

  const completeMutation = useMutation({
    mutationFn: async (assignment: Assignment) => {
      if (!organizationId) throw new Error('No organization');
      return lmsApi.completeAssignment(organizationId, assignment.id);
    },
    onSuccess: () => {
      toast.success('Assignment completed');
      void queryClient.invalidateQueries({ queryKey: ['assignments'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!organizationId) throw new Error('No organization');
      return lmsApi.createAssignment(organizationId, {
        module_id: moduleId,
        employee_id: employeeId || undefined,
        due_date: dueDate ? new Date(dueDate).toISOString() : undefined,
        notes: notes || undefined,
      });
    },
    onSuccess: () => {
      toast.success('Assignment created — in-app task only. No email was sent.');
      setDialogOpen(false);
      setModuleId('');
      setEmployeeId('');
      setDueDate('');
      setNotes('');
      void queryClient.invalidateQueries({ queryKey: ['assignments'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const allAssignments = useMemo<Assignment[]>(
    () => assignmentsQuery.data ?? [],
    [assignmentsQuery.data],
  );

  const counts = useMemo(() => {
    const completed = allAssignments.filter((item) => item.status === 'completed').length;
    const overdue = allAssignments.filter(isOverdue).length;
    return {
      total: allAssignments.length,
      completed,
      overdue,
      open: allAssignments.length - completed,
      rate: allAssignments.length ? Math.round((completed / allAssignments.length) * 100) : 0,
    };
  }, [allAssignments]);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return allAssignments.filter((assignment) => {
      if (statusFilter !== 'all' && derivedStatus(assignment) !== statusFilter) return false;
      if (!needle) return true;
      return [
        assignment.module_title,
        assignment.employee_name,
        assignment.employee_email,
        assignment.notes,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [allAssignments, search, statusFilter]);

  if (!organizationId) {
    return <Alert severity="warning">Your account is not attached to an organization.</Alert>;
  }

  return (
    <>
      <PageHeader
        title="Assignments"
        subtitle="In-app training tasks. These do not send email."
        actions={
          <Stack direction="row" spacing={1}>
            <Button
              variant="outlined"
              startIcon={<SendIcon />}
              onClick={() => navigate('/campaigns/new')}
            >
              Send simulation email
            </Button>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              disabled={!canManage}
              onClick={() => setDialogOpen(true)}
            >
              New assignment
            </Button>
          </Stack>
        }
      />

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 3 }}>
        <Card sx={{ flex: 1, p: 0 }}>
          <StatCard label="Open" value={counts.open} tone="primary" />
        </Card>
        <Card sx={{ flex: 1, p: 0 }}>
          <StatCard label="Overdue" value={counts.overdue} tone={counts.overdue ? 'error' : 'success'} />
        </Card>
        <Card sx={{ flex: 1, p: 0 }}>
          <StatCard label="Completed" value={counts.completed} tone="success" />
        </Card>
        <Card sx={{ flex: 1, p: 0 }}>
          <StatCard label="Completion rate" value={`${counts.rate}%`} tone="default" />
        </Card>
      </Stack>

      {counts.overdue > 0 ? (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {counts.overdue} assignment{counts.overdue === 1 ? '' : 's'} passed the due date without
          completion. Follow up or reassign the module — remediation that is never finished leaves
          the risk in place.
        </Alert>
      ) : null}

      <Alert severity="info" sx={{ mb: 2 }}>
        Creating an assignment only records an internal training task —{' '}
        <strong>it never sends an email</strong>. To send a real phishing-simulation email with live
        open/click tracking, use <strong>Campaigns → New campaign</strong>.
      </Alert>

      {!canManage ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          You have read-only access. Creating or completing assignments requires{' '}
          <code>lms.manage</code>.
        </Alert>
      ) : null}

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        sx={{ mb: 2 }}
        alignItems={{ xs: 'stretch', sm: 'center' }}
      >
        <TextField
          select
          size="small"
          label="Status"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          sx={{ minWidth: 180 }}
        >
          {STATUS_OPTIONS.map((option) => (
            <MenuItem key={option} value={option}>
              {option === 'all' ? 'All statuses' : option}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          size="small"
          label="Search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          sx={{ minWidth: 260 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
        <Chip label={`${visible.length} of ${counts.total} assignments`} />
      </Stack>

      {assignmentsQuery.isLoading ? (
        <LoadingState label="Loading assignments…" />
      ) : assignmentsQuery.error ? (
        <Alert severity="error">{errorMessage(assignmentsQuery.error)}</Alert>
      ) : visible.length === 0 ? (
        <Card>
          <EmptyState
            title={allAssignments.length === 0 ? 'No assignments' : 'No matching assignments'}
            description={
              allAssignments.length === 0
                ? 'Create an assignment from the Training Library or from this page.'
                : 'Adjust the status or search to widen the view.'
            }
          />
        </Card>
      ) : (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Module</TableCell>
                  <TableCell>Assignee</TableCell>
                  <TableCell align="center">Status</TableCell>
                  <TableCell>Due</TableCell>
                  <TableCell>Completed</TableCell>
                  <TableCell>Notes</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visible.map((assignment) => {
                  const status = derivedStatus(assignment);
                  const overdue = status === 'overdue';
                  return (
                    <TableRow key={assignment.id} hover>
                      <TableCell>{assignment.module_title ?? '—'}</TableCell>
                      <TableCell>
                        {assignment.employee_name ??
                          assignment.employee_email ??
                          'Whole organization'}
                      </TableCell>
                      <TableCell align="center">
                        <Chip
                          size="small"
                          variant="outlined"
                          label={status}
                          color={STATUS_COLORS[status] ?? 'default'}
                        />
                      </TableCell>
                      <TableCell sx={overdue ? { color: 'error.main', fontWeight: 700 } : undefined}>
                        {formatDate(assignment.due_date)}
                      </TableCell>
                      <TableCell>{formatDate(assignment.completed_at)}</TableCell>
                      <TableCell>{assignment.notes ?? '—'}</TableCell>
                      <TableCell align="right">
                        {assignment.status !== 'completed' ? (
                          <Tooltip title={canManage ? 'Mark complete' : 'Requires lms.manage'}>
                            <span>
                              <IconButton
                                size="small"
                                color="success"
                                disabled={completeMutation.isPending || !canManage}
                                onClick={() => completeMutation.mutate(assignment)}
                              >
                                <TaskAltIcon fontSize="small" />
                              </IconButton>
                            </span>
                          </Tooltip>
                        ) : (
                          <TaskAltIcon fontSize="small" color="success" />
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New in-app assignment</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="warning">
              This action does not send email to the employee. To deliver a real simulation email,
              launch a campaign instead.
            </Alert>
            <TextField
              select
              required
              label="Module"
              fullWidth
              value={moduleId}
              onChange={(event) => setModuleId(event.target.value)}
            >
              {(modulesQuery.data ?? []).map((module) => (
                <MenuItem key={module.id} value={module.id}>
                  {module.title}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Employee"
              fullWidth
              value={employeeId}
              onChange={(event) => setEmployeeId(event.target.value)}
              helperText="Leave empty to assign organization-wide."
            >
              <MenuItem value="">Whole organization</MenuItem>
              {(employeesQuery.data?.items ?? []).map((employee) => (
                <MenuItem key={employee.id} value={employee.id}>
                  {employee.first_name} {employee.last_name} — {employee.email}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Due date"
              type="date"
              fullWidth
              InputLabelProps={{ shrink: true }}
              value={dueDate}
              onChange={(event) => setDueDate(event.target.value)}
            />
            <TextField
              label="Notes"
              fullWidth
              multiline
              minRows={3}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!moduleId || createMutation.isPending || !canManage}
            onClick={() => createMutation.mutate()}
          >
            Create (no email)
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
