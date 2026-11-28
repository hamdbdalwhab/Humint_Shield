/**
 * Training Library: the catalogue of awareness micro-modules.
 *
 * Module content, category and duration come from the LMS; the campaign
 * subsystem only contributes assignments that can be generated from here.
 *
 * The library is only useful if an operator can see whether the material is
 * actually being consumed, so every card shows how many assignments exist for
 * that module and how many are complete. Search and category chips keep the
 * catalogue usable as it grows.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardActions from '@mui/material/CardActions';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Grid from '@mui/material/Grid';
import InputAdornment from '@mui/material/InputAdornment';
import LinearProgress from '@mui/material/LinearProgress';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import AssignmentTurnedInIcon from '@mui/icons-material/AssignmentTurnedIn';
import MenuBookIcon from '@mui/icons-material/MenuBook';
import SearchIcon from '@mui/icons-material/Search';
import VisibilityIcon from '@mui/icons-material/Visibility';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';

import { employeesApi, lmsApi } from '@/api/endpoints';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import type { Assignment, TrainingModule } from '@/types';

export function TrainingLibraryPage() {
  const { organizationId, can } = useAuth();
  const queryClient = useQueryClient();
  const canManage = can('lms.manage');

  const [viewing, setViewing] = useState<TrainingModule | null>(null);
  const [assigning, setAssigning] = useState<TrainingModule | null>(null);
  const [employeeId, setEmployeeId] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [notes, setNotes] = useState('');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');

  const modulesQuery = useQuery({
    queryKey: ['modules', organizationId],
    queryFn: () => lmsApi.modules(organizationId as string),
    enabled: Boolean(organizationId),
  });

  const assignmentsQuery = useQuery({
    queryKey: ['assignments', organizationId, 'library-rollup'],
    queryFn: () => lmsApi.assignments(organizationId as string),
    enabled: Boolean(organizationId),
  });

  const employeesQuery = useQuery({
    queryKey: ['employees', organizationId, 'assignment-picker'],
    queryFn: () => employeesApi.list(organizationId as string, { per_page: 200, is_active: true }),
    enabled: Boolean(organizationId),
  });

  const assignMutation = useMutation({
    mutationFn: async () => {
      if (!organizationId || !assigning) throw new Error('No organization');
      return lmsApi.createAssignment(organizationId, {
        module_id: assigning.id,
        employee_id: employeeId || undefined,
        due_date: dueDate ? new Date(dueDate).toISOString() : undefined,
        notes: notes || undefined,
      });
    },
    onSuccess: () => {
      toast.success(
        employeeId ? 'Assignment created' : 'Module assigned to the whole organization',
      );
      setAssigning(null);
      setEmployeeId('');
      setDueDate('');
      setNotes('');
      void queryClient.invalidateQueries({ queryKey: ['assignments'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const modules = useMemo<TrainingModule[]>(
    () => modulesQuery.data ?? [],
    [modulesQuery.data],
  );
  const assignments = useMemo<Assignment[]>(
    () => assignmentsQuery.data ?? [],
    [assignmentsQuery.data],
  );

  const rollup = useMemo(() => {
    const map = new Map<string, { total: number; completed: number }>();
    for (const assignment of assignments) {
      const entry = map.get(assignment.module_id) ?? { total: 0, completed: 0 };
      entry.total += 1;
      if (assignment.status === 'completed') entry.completed += 1;
      map.set(assignment.module_id, entry);
    }
    return map;
  }, [assignments]);

  const categories = useMemo(() => {
    const seen = new Set<string>();
    for (const module of modules) {
      if (module.category) seen.add(module.category);
    }
    return Array.from(seen).sort((a, b) => a.localeCompare(b));
  }, [modules]);

  const visibleModules = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return modules.filter((module) => {
      if (category !== 'all' && module.category !== category) return false;
      if (!needle) return true;
      return [module.title, module.summary, module.category]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [category, modules, search]);

  const totals = useMemo(() => {
    const completed = assignments.filter((item) => item.status === 'completed').length;
    return {
      modules: modules.length,
      assignments: assignments.length,
      completed,
      rate: assignments.length ? Math.round((completed / assignments.length) * 100) : 0,
      minutes: modules.reduce((sum, module) => sum + (module.duration_minutes || 0), 0),
    };
  }, [assignments, modules]);

  if (!organizationId) {
    return <Alert severity="warning">Your account is not attached to an organization.</Alert>;
  }

  return (
    <>
      <PageHeader
        title="Training Library"
        subtitle="Focused micro-modules used for remediation and continuous awareness."
      />

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
        <Card sx={{ flex: 1 }}>
          <CardContent>
            <Typography variant="overline" color="text.secondary">
              Modules
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800 }}>
              {totals.modules}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {totals.minutes} minutes of content
            </Typography>
          </CardContent>
        </Card>
        <Card sx={{ flex: 1 }}>
          <CardContent>
            <Typography variant="overline" color="text.secondary">
              Assignments
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800 }}>
              {totals.assignments}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {totals.completed} completed
            </Typography>
          </CardContent>
        </Card>
        <Card sx={{ flex: 1 }}>
          <CardContent>
            <Typography variant="overline" color="text.secondary">
              Completion rate
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800 }}>
              {totals.rate}%
            </Typography>
            <LinearProgress
              variant="determinate"
              value={totals.rate}
              sx={{ mt: 1, height: 6, borderRadius: 3 }}
            />
          </CardContent>
        </Card>
      </Stack>

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={2}
        sx={{ mb: 2 }}
        alignItems={{ xs: 'stretch', md: 'center' }}
      >
        <TextField
          size="small"
          label="Search the library"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          sx={{ minWidth: 280 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
        <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', gap: 0.75 }}>
          <Chip
            size="small"
            clickable
            label={`All (${modules.length})`}
            color={category === 'all' ? 'primary' : 'default'}
            variant={category === 'all' ? 'filled' : 'outlined'}
            onClick={() => setCategory('all')}
          />
          {categories.map((item) => (
            <Chip
              key={item}
              size="small"
              clickable
              label={item}
              color={category === item ? 'primary' : 'default'}
              variant={category === item ? 'filled' : 'outlined'}
              onClick={() => setCategory(item)}
            />
          ))}
        </Stack>
      </Stack>

      {!canManage ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          You can read the library. Creating assignments requires the <code>lms.manage</code>{' '}
          permission.
        </Alert>
      ) : null}

      {modulesQuery.isLoading ? (
        <LoadingState label="Loading modules…" />
      ) : modulesQuery.error ? (
        <Alert severity="error">{errorMessage(modulesQuery.error)}</Alert>
      ) : visibleModules.length === 0 ? (
        <Card>
          <EmptyState
            title={modules.length === 0 ? 'No modules yet' : 'No modules match'}
            description={
              modules.length === 0
                ? 'Training modules are seeded on first startup.'
                : 'Clear the search or choose another category.'
            }
          />
        </Card>
      ) : (
        <Grid container spacing={2}>
          {visibleModules.map((module) => {
            const stats = rollup.get(module.id) ?? { total: 0, completed: 0 };
            const rate = stats.total ? Math.round((stats.completed / stats.total) * 100) : 0;
            return (
              <Grid item xs={12} sm={6} lg={4} key={module.id}>
                <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <CardContent sx={{ flexGrow: 1 }}>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                      <MenuBookIcon color="primary" fontSize="small" />
                      <Typography variant="h3" sx={{ fontSize: '1rem' }}>
                        {module.title}
                      </Typography>
                    </Stack>
                    <Stack direction="row" spacing={0.5} sx={{ mb: 1, flexWrap: 'wrap', gap: 0.5 }}>
                      {module.category ? <Chip size="small" label={module.category} /> : null}
                      <Chip
                        size="small"
                        variant="outlined"
                        label={`${module.duration_minutes} min`}
                      />
                      <Chip size="small" variant="outlined" label={`L${module.difficulty_level}`} />
                      {!module.is_active ? <Chip size="small" label="inactive" /> : null}
                    </Stack>
                    <Typography variant="body2" color="text.secondary">
                      {module.summary ?? 'No summary provided.'}
                    </Typography>
                    <Box sx={{ mt: 1.5 }}>
                      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
                        <Typography variant="caption" color="text.secondary">
                          {stats.total
                            ? `${stats.completed}/${stats.total} assignments completed`
                            : 'Not assigned yet'}
                        </Typography>
                        {stats.total ? (
                          <Typography variant="caption" sx={{ fontWeight: 700 }}>
                            {rate}%
                          </Typography>
                        ) : null}
                      </Stack>
                      <LinearProgress
                        variant="determinate"
                        value={rate}
                        color={rate >= 80 ? 'success' : rate >= 40 ? 'warning' : 'error'}
                        sx={{ height: 5, borderRadius: 3 }}
                      />
                    </Box>
                  </CardContent>
                  <CardActions sx={{ justifyContent: 'flex-end' }}>
                    <Button
                      size="small"
                      startIcon={<VisibilityIcon />}
                      onClick={() => setViewing(module)}
                    >
                      Read
                    </Button>
                    <Button
                      size="small"
                      variant="contained"
                      startIcon={<AssignmentTurnedInIcon />}
                      disabled={!canManage}
                      onClick={() => setAssigning(module)}
                    >
                      Assign
                    </Button>
                  </CardActions>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      )}

      <Dialog open={Boolean(viewing)} onClose={() => setViewing(null)} maxWidth="md" fullWidth>
        <DialogTitle>{viewing?.title}</DialogTitle>
        <DialogContent dividers>
          {viewing ? (
            <Stack spacing={2}>
              {viewing.summary ? (
                <Typography variant="body2" color="text.secondary">
                  {viewing.summary}
                </Typography>
              ) : null}
              <div dangerouslySetInnerHTML={{ __html: viewing.content_html }} />
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setViewing(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(assigning)} onClose={() => setAssigning(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Assign — {assigning?.title}</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="info">
              This records an in-app training task only. To deliver a real simulation email, launch a
              campaign.
            </Alert>
            <TextField
              select
              label="Employee"
              fullWidth
              value={employeeId}
              onChange={(event) => setEmployeeId(event.target.value)}
              helperText="Leave empty to assign the module organization-wide."
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
          <Button onClick={() => setAssigning(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={assignMutation.isPending || !canManage}
            onClick={() => assignMutation.mutate()}
          >
            Assign module
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
