/**
 * My Training: the signed-in user's personal remediation queue.
 *
 * Users are matched to their training profile by email address. When no
 * matching employee record exists (for example a platform-only administrator)
 * an explanatory notice is shown instead of an empty table.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import SchoolIcon from '@mui/icons-material/School';
import TaskAltIcon from '@mui/icons-material/TaskAlt';
import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';

import { employeesApi, lmsApi } from '@/api/endpoints';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { StatCard } from '@/components/StatCard';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDate } from '@/lib/format';
import type { Assignment } from '@/types';

export function MyTrainingPage() {
  const { organizationId, user } = useAuth();
  const queryClient = useQueryClient();

  const employeesQuery = useQuery({
    queryKey: ['employees', organizationId, 'self'],
    queryFn: () =>
      employeesApi.list(organizationId as string, {
        per_page: 200,
        search: user?.email ?? undefined,
      }),
    enabled: Boolean(organizationId && user?.email),
  });

  const me = useMemo(
    () =>
      employeesQuery.data?.items.find(
        (employee) => employee.email.toLowerCase() === (user?.email ?? '').toLowerCase(),
      ) ?? null,
    [employeesQuery.data, user?.email],
  );

  const assignmentsQuery = useQuery({
    queryKey: ['assignments', organizationId, 'self', me?.id],
    queryFn: () => lmsApi.assignments(organizationId as string, { employee_id: me?.id }),
    enabled: Boolean(organizationId && me?.id),
  });

  const completeMutation = useMutation({
    mutationFn: async (assignment: Assignment) => {
      if (!organizationId) throw new Error('No organization');
      return lmsApi.completeAssignment(organizationId, assignment.id);
    },
    onSuccess: () => {
      toast.success('Training marked complete');
      void queryClient.invalidateQueries({ queryKey: ['assignments'] });
      void queryClient.invalidateQueries({ queryKey: ['employees'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (!organizationId) {
    return <Alert severity="warning">Your account is not attached to an organization.</Alert>;
  }

  const assignments = assignmentsQuery.data ?? [];
  const completed = assignments.filter((item) => item.status === 'completed').length;
  const completionRate = assignments.length ? (completed / assignments.length) * 100 : 0;

  return (
    <>
      <PageHeader
        title="My Training"
        subtitle="Your personal security-awareness queue and progress."
      />

      {employeesQuery.isLoading ? (
        <LoadingState label="Locating your training profile…" />
      ) : !me ? (
        <Alert severity="info">
          No employee training profile is linked to {user?.email ?? 'your account'} yet. Ask an
          administrator to add you to the employee directory to receive assignments.
        </Alert>
      ) : (
        <Stack spacing={3}>
          <Stack direction="row" spacing={1} alignItems="center">
            <SchoolIcon color="primary" />
            <Typography variant="h3" sx={{ fontSize: '1.05rem' }}>
              {me.first_name} {me.last_name}
            </Typography>
            <Chip size="small" label={`Immunity score ${me.immunity_score}`} />
            {me.behavioral_category ? (
              <Chip size="small" variant="outlined" label={me.behavioral_category} />
            ) : null}
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <Box sx={{ flexGrow: 1 }}>
              <StatCard
                label="Assignments"
                value={assignments.length}
                helper={`${completed} completed`}
                tone="primary"
              />
            </Box>
            <Box sx={{ flexGrow: 1 }}>
              <StatCard
                label="Completion"
                value={`${completionRate.toFixed(0)}%`}
                helper="of your assigned modules"
                tone="success"
              />
            </Box>
            <Box sx={{ flexGrow: 1 }}>
              <StatCard label="Last test" value={formatDate(me.last_test_date)} helper="most recent simulation" />
            </Box>
          </Stack>

          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                Progress
              </Typography>
              <LinearProgress
                variant="determinate"
                value={completionRate}
                sx={{ height: 10, borderRadius: 5 }}
              />
            </CardContent>
          </Card>

          {assignmentsQuery.isLoading ? (
            <LoadingState label="Loading your assignments…" />
          ) : assignmentsQuery.error ? (
            <Alert severity="error">{errorMessage(assignmentsQuery.error)}</Alert>
          ) : assignments.length === 0 ? (
            <Card>
              <EmptyState
                title="Nothing assigned"
                description="You have no outstanding training. Well done."
              />
            </Card>
          ) : (
            <Card>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Module</TableCell>
                      <TableCell align="center">Status</TableCell>
                      <TableCell>Due</TableCell>
                      <TableCell>Completed</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {assignments.map((assignment) => (
                      <TableRow key={assignment.id} hover>
                        <TableCell>{assignment.module_title ?? '—'}</TableCell>
                        <TableCell align="center">
                          <Chip
                            size="small"
                            variant="outlined"
                            color={assignment.status === 'completed' ? 'success' : 'info'}
                            label={assignment.status}
                          />
                        </TableCell>
                        <TableCell>{formatDate(assignment.due_date)}</TableCell>
                        <TableCell>{formatDate(assignment.completed_at)}</TableCell>
                        <TableCell align="right">
                          <Button
                            size="small"
                            startIcon={<TaskAltIcon />}
                            variant={assignment.status === 'completed' ? 'text' : 'contained'}
                            disabled={
                              assignment.status === 'completed' || completeMutation.isPending
                            }
                            onClick={() => completeMutation.mutate(assignment)}
                          >
                            {assignment.status === 'completed' ? 'Done' : 'Mark complete'}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Card>
          )}
        </Stack>
      )}
    </>
  );
}
