/**
 * Report Inbox: triage queue for suspicious messages reported by employees.
 *
 * Filing a report is a positive security behaviour; this page is where
 * administrators acknowledge and classify those reports.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';

import { lmsApi } from '@/api/endpoints';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { StatCard } from '@/components/StatCard';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import type { PhishingReport } from '@/types';

const STATUS_OPTIONS = ['all', 'new', 'triage', 'resolved', 'false_positive'] as const;

const STATUS_COLORS: Record<string, 'default' | 'info' | 'success' | 'warning'> = {
  new: 'warning',
  triage: 'info',
  resolved: 'success',
  false_positive: 'default',
};

export function ReportInboxPage() {
  const { organizationId } = useAuth();
  const queryClient = useQueryClient();

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [triaging, setTriaging] = useState<PhishingReport | null>(null);
  const [status, setStatus] = useState('triage');
  const [notes, setNotes] = useState('');

  const reportsQuery = useQuery({
    queryKey: ['reports', organizationId, statusFilter],
    queryFn: () =>
      lmsApi.reports(organizationId as string, statusFilter === 'all' ? undefined : statusFilter),
    enabled: Boolean(organizationId),
  });

  const counts = useMemo(() => {
    const rows = reportsQuery.data ?? [];
    return {
      total: rows.length,
      pending: rows.filter((report) => report.status === 'new').length,
      resolved: rows.filter((report) => report.status === 'resolved').length,
      falsePositive: rows.filter((report) => report.status === 'false_positive').length,
    };
  }, [reportsQuery.data]);

  const triageMutation = useMutation({
    mutationFn: async () => {
      if (!organizationId || !triaging) throw new Error('No organization');
      return lmsApi.updateReport(organizationId, triaging.id, {
        status,
        triage_notes: notes || undefined,
      });
    },
    onSuccess: () => {
      toast.success('Report updated');
      setTriaging(null);
      setNotes('');
      void queryClient.invalidateQueries({ queryKey: ['reports'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  function openTriage(report: PhishingReport) {
    setTriaging(report);
    setStatus(report.status === 'new' ? 'triage' : report.status);
    setNotes(report.triage_notes ?? '');
  }

  if (!organizationId) {
    return <Alert severity="warning">Your account is not attached to an organization.</Alert>;
  }

  return (
    <>
      <PageHeader
        title="Report Inbox"
        subtitle="Employee-reported suspicious messages awaiting triage."
      />

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 3 }}>
        <Box sx={{ flexGrow: 1 }}>
          <StatCard label="Shown" value={counts.total} />
        </Box>
        <Box sx={{ flexGrow: 1 }}>
          <StatCard label="Awaiting triage" value={counts.pending} tone="warning" />
        </Box>
        <Box sx={{ flexGrow: 1 }}>
          <StatCard label="Resolved" value={counts.resolved} tone="success" />
        </Box>
        <Box sx={{ flexGrow: 1 }}>
          <StatCard label="False positives" value={counts.falsePositive} />
        </Box>
      </Stack>

      <Stack direction="row" spacing={2} sx={{ mb: 2 }} alignItems="center">
        <TextField
          select
          size="small"
          label="Status"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          sx={{ minWidth: 200 }}
        >
          {STATUS_OPTIONS.map((option) => (
            <MenuItem key={option} value={option}>
              {option === 'all' ? 'All statuses' : option.replace('_', ' ')}
            </MenuItem>
          ))}
        </TextField>
        <Chip label={`${counts.total} reports`} />
      </Stack>

      {reportsQuery.isLoading ? (
        <LoadingState label="Loading reports…" />
      ) : reportsQuery.error ? (
        <Alert severity="error">{errorMessage(reportsQuery.error)}</Alert>
      ) : (reportsQuery.data ?? []).length === 0 ? (
        <Card>
          <EmptyState
            title="Inbox clear"
            description="No reported messages match this filter."
          />
        </Card>
      ) : (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Subject</TableCell>
                  <TableCell>Sender</TableCell>
                  <TableCell align="center">Status</TableCell>
                  <TableCell>Simulation</TableCell>
                  <TableCell>Received</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {reportsQuery.data?.map((report) => (
                  <TableRow key={report.id} hover>
                    <TableCell>
                      <Typography variant="body2">
                        {report.reported_email_subject ?? '—'}
                      </Typography>
                      {report.description ? (
                        <Typography variant="caption" color="text.secondary">
                          {report.description}
                        </Typography>
                      ) : null}
                    </TableCell>
                    <TableCell>{report.reported_sender ?? '—'}</TableCell>
                    <TableCell align="center">
                      <Chip
                        size="small"
                        variant="outlined"
                        label={report.status.replace('_', ' ')}
                        color={STATUS_COLORS[report.status] ?? 'default'}
                      />
                    </TableCell>
                    <TableCell>{report.is_training_simulation ? 'Yes' : 'No'}</TableCell>
                    <TableCell>{formatDateTime(report.created_at)}</TableCell>
                    <TableCell align="right">
                      <Button size="small" onClick={() => openTriage(report)}>
                        Triage
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}

      <Dialog open={Boolean(triaging)} onClose={() => setTriaging(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Triage report</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="subtitle2">
              {triaging?.reported_email_subject ?? 'Reported message'}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              From: {triaging?.reported_sender ?? 'unknown sender'}
            </Typography>
            <TextField
              select
              label="Status"
              fullWidth
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              {STATUS_OPTIONS.filter((option) => option !== 'all').map((option) => (
                <MenuItem key={option} value={option}>
                  {option.replace('_', ' ')}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Triage notes"
              fullWidth
              multiline
              minRows={4}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTriaging(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={triageMutation.isPending}
            onClick={() => triageMutation.mutate()}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
