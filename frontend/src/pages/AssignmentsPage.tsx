/**
 * Assignments: remediation tracking for training modules.
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
import SendIcon from '@mui/icons-material/Send';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';

import { employeesApi, lmsApi } from '@/api/endpoints';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDate } from '@/lib/format';
import type { Assignment } from '@/types';

const STATUS_OPTIONS = ['all', 'assigned', 'completed'] as const;

const STATUS_COLORS: Record<string, 'default' | 'info' | 'success' | 'warning'> = {
  assigned: 'info',
  completed: 'success',
  overdue: 'warning',
};

export function AssignmentsPage() {
  const { organizationId } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [moduleId, setModuleId] = useState('');
  const [employeeId, setEmployeeId] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [notes, setNotes] = useState('');

  const assignmentsQuery = useQuery({
    queryKey: ['assignments', organizationId, statusFilter],
    queryFn: () =>
      lmsApi.assignments(organizationId as string, {
        status: statusFilter === 'all' ? undefined : statusFilter,
      }),
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
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>
              New assignment
            </Button>
          </Stack>
        }
      />

      <Alert severity="info" sx={{ mb: 2 }}>
        Creating an assignment only records an internal training task — <strong>it never sends an email</strong>.
        To send a real phishing-simulation email with live open/click tracking, use{' '}
        <strong>Campaigns → New campaign</strong>.
      </Alert>

      <Stack direction="row" spacing={2} sx={{ mb: 2 }} alignItems="center">
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
        <Chip label={`${assignmentsQuery.data?.length ?? 0} assignments`} />
      </Stack>

      {assignmentsQuery.isLoading ? (
        <LoadingState label="Loading assignments…" />
      ) : assignmentsQuery.error ? (
        <Alert severity="error">{errorMessage(assignmentsQuery.error)}</Alert>
      ) : (assignmentsQuery.data ?? []).length === 0 ? (
        <Card>
          <EmptyState
            title="No assignments"
            description="Create an assignment from the Training Library or from this page."
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
                {assignmentsQuery.data?.map((assignment) => (
                  <TableRow key={assignment.id} hover>
                    <TableCell>{assignment.module_title ?? '—'}</TableCell>
                    <TableCell>
                      {assignment.employee_name ?? assignment.employee_email ?? 'Whole organization'}
                    </TableCell>
                    <TableCell align="center">
                      <Chip
                        size="small"
                        variant="outlined"
                        label={assignment.status}
                        color={STATUS_COLORS[assignment.status] ?? 'default'}
                      />
                    </TableCell>
                    <TableCell>{formatDate(assignment.due_date)}</TableCell>
                    <TableCell>{formatDate(assignment.completed_at)}</TableCell>
                    <TableCell>{assignment.notes ?? '—'}</TableCell>
                    <TableCell align="right">
                      {assignment.status !== 'completed' ? (
                        <Tooltip title="Mark complete">
                          <IconButton
                            size="small"
                            color="success"
                            disabled={completeMutation.isPending}
                            onClick={() => completeMutation.mutate(assignment)}
                          >
                            <TaskAltIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      ) : (
                        <TaskAltIcon fontSize="small" color="success" />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
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
              This action does not send email to the employee. To deliver a real simulation email, launch a
              campaign instead.
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
            disabled={!moduleId || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Create (no email)
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
