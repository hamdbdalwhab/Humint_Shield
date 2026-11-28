/**
 * Report Inbox: triage queue for suspicious messages reported by employees.
 *
 * Filing a report is a positive security behaviour; this page is where
 * administrators acknowledge and classify those reports.
 *
 * All reports are fetched once and filtered in the browser so the headline
 * counters describe the whole inbox rather than the current view. Each row
 * carries its age so an unreviewed report cannot quietly rot, and every write
 * action is hidden unless the operator holds `inbox.manage`.
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
import Typography from '@mui/material/Typography';
import SearchIcon from '@mui/icons-material/Search';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import IconButton from '@mui/material/IconButton';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
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

const STATUS_LABELS: Record<string, string> = {
  all: 'All statuses',
  new: 'New',
  triage: 'In triage',
  resolved: 'Resolved',
  false_positive: 'False positive',
};

/** Hours since a report was filed (never negative). */
function hoursOpen(createdAt: string): number {
  const created = new Date(createdAt).getTime();
  if (Number.isNaN(created)) return 0;
  return Math.max(0, Math.floor((Date.now() - created) / 3_600_000));
}

function ageLabel(createdAt: string): string {
  const hours = hoursOpen(createdAt);
  if (hours < 1) return 'just now';
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

export function ReportInboxPage() {
  const { organizationId, can } = useAuth();
  const queryClient = useQueryClient();
  const canManage = can('inbox.manage');

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [triaging, setTriaging] = useState<PhishingReport | null>(null);
  const [status, setStatus] = useState('triage');
  const [notes, setNotes] = useState('');

  const reportsQuery = useQuery({
    queryKey: ['reports', organizationId],
    queryFn: () => lmsApi.reports(organizationId as string),
    enabled: Boolean(organizationId),
  });

  const allReports = useMemo(() => reportsQuery.data ?? [], [reportsQuery.data]);

  const counts = useMemo(() => {
    const pendingRows = allReports.filter((report) => report.status === 'new');
    const ages = pendingRows.map((report) => hoursOpen(report.created_at));
    return {
      total: allReports.length,
      pending: pendingRows.length,
      triage: allReports.filter((report) => report.status === 'triage').length,
      resolved: allReports.filter((report) => report.status === 'resolved').length,
      falsePositive: allReports.filter((report) => report.status === 'false_positive').length,
      overdue: ages.filter((age) => age >= 48).length,
      oldest: ages.length ? Math.max(...ages) : 0,
    };
  }, [allReports]);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return allReports.filter((report) => {
      if (statusFilter !== 'all' && report.status !== statusFilter) return false;
      if (!needle) return true;
      return [report.reported_email_subject, report.reported_sender, report.description]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [allReports, search, statusFilter]);

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

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
        <Box sx={{ flexGrow: 1 }}>
          <StatCard label="Total reports" value={counts.total} />
        </Box>
        <Box sx={{ flexGrow: 1 }}>
          <StatCard label="Awaiting triage" value={counts.pending} tone="warning" />
        </Box>
        <Box sx={{ flexGrow: 1 }}>
          <StatCard label="Overdue (48h+)" value={counts.overdue} tone={counts.overdue ? 'error' : 'success'} />
        </Box>
        <Box sx={{ flexGrow: 1 }}>
          <StatCard label="Resolved" value={counts.resolved} tone="success" />
        </Box>
      </Stack>

      {counts.overdue > 0 ? (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {counts.overdue} report{counts.overdue === 1 ? '' : 's'} have waited more than 48 hours.
          Oldest open report: {ageLabel(
            new Date(Date.now() - counts.oldest * 3_600_000).toISOString(),
          )}. Prompt triage is what turns a report into a blocked campaign.
        </Alert>
      ) : null}

      {!canManage ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          You have read-only access to the inbox. Triage requires the <code>inbox.manage</code>{' '}
          permission.
        </Alert>
      ) : null}

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={2}
        sx={{ mb: 2 }}
        alignItems={{ xs: 'stretch', md: 'center' }}
      >
        <TextField
          size="small"
          placeholder="Search subject, sender or description…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          sx={{ minWidth: 300 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
        <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', gap: 0.75 }}>
          {STATUS_OPTIONS.map((option) => {
            const selected = statusFilter === option;
            return (
              <Chip
                key={option}
                size="small"
                clickable
                color={selected ? 'primary' : 'default'}
                variant={selected ? 'filled' : 'outlined'}
                label={STATUS_LABELS[option]}
                onClick={() => setStatusFilter(option)}
              />
            );
          })}
        </Stack>
        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="caption" color="text.secondary">
          Showing {visible.length} of {counts.total}
        </Typography>
      </Stack>

      {reportsQuery.isLoading ? (
        <LoadingState label="Loading reports…" />
      ) : reportsQuery.error ? (
        <Alert severity="error">{errorMessage(reportsQuery.error)}</Alert>
      ) : visible.length === 0 ? (
        <Card>
          <EmptyState
            title={allReports.length === 0 ? 'Inbox clear' : 'No matching reports'}
            description={
              allReports.length === 0
                ? 'No suspicious messages have been reported yet.'
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
                  <TableCell>Subject</TableCell>
                  <TableCell>Sender</TableCell>
                  <TableCell align="center">Status</TableCell>
                  <TableCell align="center">Simulation</TableCell>
                  <TableCell align="center">Age</TableCell>
                  <TableCell>Received</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visible.map((report) => {
                  const age = hoursOpen(report.created_at);
                  const sla = report.status === 'new' && age >= 48;
                  return (
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
                          label={STATUS_LABELS[report.status] ?? report.status}
                          color={STATUS_COLORS[report.status] ?? 'default'}
                        />
                      </TableCell>
                      <TableCell align="center">
                        {report.is_training_simulation ? (
                          <Chip size="small" color="info" variant="outlined" label="Training" />
                        ) : (
                          <Typography variant="caption" color="text.secondary">
                            Real
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell align="center">
                        <Chip
                          size="small"
                          color={sla ? 'error' : 'default'}
                          variant={sla ? 'filled' : 'outlined'}
                          label={ageLabel(report.created_at)}
                        />
                      </TableCell>
                      <TableCell>{formatDateTime(report.created_at)}</TableCell>
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                          {report.employee_id ? (
                            <Tooltip title="Open the reporting employee's dossier">
                              <IconButton
                                size="small"
                                component={RouterLink}
                                to={`/employees/${report.employee_id}`}
                              >
                                <OpenInNewIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          ) : null}
                          <Button
                            size="small"
                            disabled={!canManage}
                            onClick={() => openTriage(report)}
                          >
                            Triage
                          </Button>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}
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
            {triaging?.description ? (
              <Alert severity="info">{triaging.description}</Alert>
            ) : null}
            <TextField
              select
              label="Status"
              fullWidth
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              {STATUS_OPTIONS.filter((option) => option !== 'all').map((option) => (
                <MenuItem key={option} value={option}>
                  {STATUS_LABELS[option]}
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
              helperText="Record the verdict and any containment action so the next analyst can audit it."
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTriaging(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={triageMutation.isPending || !canManage}
            onClick={() => triageMutation.mutate()}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
