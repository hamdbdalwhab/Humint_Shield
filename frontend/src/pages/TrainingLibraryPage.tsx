/**
 * Training Library: the catalogue of awareness micro-modules.
 *
 * Module content, category and duration come from the LMS; the campaign
 * subsystem only contributes assignments that can be generated from here.
 */
import Alert from '@mui/material/Alert';
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
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import AssignmentTurnedInIcon from '@mui/icons-material/AssignmentTurnedIn';
import MenuBookIcon from '@mui/icons-material/MenuBook';
import VisibilityIcon from '@mui/icons-material/Visibility';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';

import { employeesApi, lmsApi } from '@/api/endpoints';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import type { TrainingModule } from '@/types';

export function TrainingLibraryPage() {
  const { organizationId } = useAuth();
  const queryClient = useQueryClient();

  const [viewing, setViewing] = useState<TrainingModule | null>(null);
  const [assigning, setAssigning] = useState<TrainingModule | null>(null);
  const [employeeId, setEmployeeId] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [notes, setNotes] = useState('');

  const modulesQuery = useQuery({
    queryKey: ['modules', organizationId],
    queryFn: () => lmsApi.modules(organizationId as string),
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

  if (!organizationId) {
    return <Alert severity="warning">Your account is not attached to an organization.</Alert>;
  }

  return (
    <>
      <PageHeader
        title="Training Library"
        subtitle="Focused micro-modules used for remediation and continuous awareness."
      />

      {modulesQuery.isLoading ? (
        <LoadingState label="Loading modules…" />
      ) : modulesQuery.error ? (
        <Alert severity="error">{errorMessage(modulesQuery.error)}</Alert>
      ) : (modulesQuery.data ?? []).length === 0 ? (
        <Card>
          <EmptyState
            title="No modules yet"
            description="Training modules are seeded on first startup."
          />
        </Card>
      ) : (
        <Grid container spacing={2}>
          {modulesQuery.data?.map((module) => (
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
                    <Chip size="small" variant="outlined" label={`${module.duration_minutes} min`} />
                    <Chip size="small" variant="outlined" label={`L${module.difficulty_level}`} />
                    {!module.is_active ? <Chip size="small" label="inactive" /> : null}
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    {module.summary ?? 'No summary provided.'}
                  </Typography>
                </CardContent>
                <CardActions sx={{ justifyContent: 'flex-end' }}>
                  <Button size="small" startIcon={<VisibilityIcon />} onClick={() => setViewing(module)}>
                    Read
                  </Button>
                  <Button
                    size="small"
                    variant="contained"
                    startIcon={<AssignmentTurnedInIcon />}
                    onClick={() => setAssigning(module)}
                  >
                    Assign
                  </Button>
                </CardActions>
              </Card>
            </Grid>
          ))}
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
            disabled={assignMutation.isPending}
            onClick={() => assignMutation.mutate()}
          >
            Assign module
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
