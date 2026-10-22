/** Campaign operations table: launch, monitor, inspect and clean up runs. */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
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
import { alpha } from '@mui/material/styles';
import { motion } from 'framer-motion';
import {
  ArrowUpRight,
  Eye,
  Megaphone,
  Play,
  Radar,
  Rocket,
  Search,
  ShieldAlert,
  Trash2,
  Zap,
} from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import Link from '@mui/material/Link';
import toast from 'react-hot-toast';

import { campaignsApi } from '@/api/endpoints';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { CampaignStatusBadge } from '@/components/StatusBadge';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDate } from '@/lib/format';
import type { Campaign } from '@/types';

const FILTERS = [
  { value: 'all', label: 'الكل' },
  { value: 'draft', label: 'مسودة' },
  { value: 'active', label: 'نشطة' },
  { value: 'completed', label: 'مكتملة' },
] as const;

function SummaryTile({
  label,
  value,
  color,
  icon,
}: {
  label: string;
  value: number;
  color: string;
  icon: ReactNode;
}) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.25,
        p: 1.5,
        borderRadius: 3,
        border: `1px solid ${alpha(color, 0.16)}`,
        bgcolor: alpha(color, 0.035),
      }}
    >
      <Box
        sx={{
          width: 36,
          height: 36,
          borderRadius: 2,
          display: 'grid',
          placeItems: 'center',
          color,
          bgcolor: alpha(color, 0.10),
          border: `1px solid ${alpha(color, 0.22)}`,
        }}
      >
        {icon}
      </Box>
      <Box>
        <Typography sx={{ fontSize: '1.25rem', fontWeight: 800, lineHeight: 1.15 }}>{value}</Typography>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem' }}>
          {label}
        </Typography>
      </Box>
    </Box>
  );
}

export function CampaignsPage() {
  const { organizationId } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [pendingDelete, setPendingDelete] = useState<Campaign | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['value']>('all');

  const campaignsQuery = useQuery({
    queryKey: ['campaigns', organizationId],
    queryFn: () => campaignsApi.list(organizationId as string),
    enabled: Boolean(organizationId),
    refetchInterval: 20_000,
  });

  const deleteMutation = useMutation({
    mutationFn: async (campaign: Campaign) => {
      if (!organizationId) throw new Error('No organization');
      await campaignsApi.remove(organizationId, campaign.id);
    },
    onSuccess: () => {
      toast.success('تم حذف المسودة');
      setPendingDelete(null);
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const launchMutation = useMutation({
    mutationFn: async (campaign: Campaign) => {
      if (!organizationId) throw new Error('No organization');
      return campaignsApi.launch(organizationId, campaign.id);
    },
    onSuccess: (result) => {
      setLaunchError(null);
      if (result.failed > 0) {
        toast.error(`أُرسل ${result.sent} من ${result.total}؛ فشل ${result.failed}.`);
      } else {
        toast.success(`أُرسل ${result.sent} من ${result.total} رسالة.`);
      }
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      navigate(`/campaigns/${result.campaign_id}/live`);
    },
    onError: (error) => {
      const message = errorMessage(error);
      setLaunchError(message);
      toast.error(message);
    },
  });

  const campaigns = useMemo(() => campaignsQuery.data ?? [], [campaignsQuery.data]);
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return campaigns.filter((campaign) => {
      if (filter !== 'all' && campaign.status !== filter) return false;
      if (!term) return true;
      return campaign.name.toLowerCase().includes(term);
    });
  }, [campaigns, filter, search]);

  const counts = useMemo(
    () => ({
      total: campaigns.length,
      draft: campaigns.filter((item) => item.status === 'draft').length,
      active: campaigns.filter((item) => item.status === 'active').length,
      completed: campaigns.filter((item) => item.status === 'completed').length,
    }),
    [campaigns],
  );

  return (
    <>
      <PageHeader
        title="الحملات"
        subtitle="محاكاة مُصرّح بها تُرسل رسائل حقيقية إلى عناوين الشركة. كل فتح ونقرة وقيمة مُدخلة تُسجّل تلقائياً."
        eyebrow="OPERATIONS · CAMPAIGNS"
        actions={
          <Stack direction="row" spacing={1}>
            <Button
              variant="outlined"
              startIcon={<Radar size={16} />}
              onClick={() => {
                const active = campaigns.find((item) => item.status === 'active');
                if (active) navigate(`/campaigns/${active.id}/live`);
                else toast('لا توجد حملة نشطة حالياً.');
              }}
            >
              مراقبة حيّة
            </Button>
            <Button variant="contained" startIcon={<Zap size={16} />} component={RouterLink} to="/campaigns/new">
              حملة جديدة
            </Button>
          </Stack>
        }
      />

      {launchError ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setLaunchError(null)}>
          <strong>تم حفظ المسودة، لكن لم تُرسل أي رسالة.</strong> {launchError}
        </Alert>
      ) : null}

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', md: 'repeat(4, minmax(0,1fr))' },
          gap: 1.25,
          mb: 2,
        }}
      >
        <SummaryTile label="إجمالي الحملات" value={counts.total} color="#00F0FF" icon={<Megaphone size={17} />} />
        <SummaryTile label="مسودات جاهزة" value={counts.draft} color="#8B9BB4" icon={<Rocket size={17} />} />
        <SummaryTile label="حملات نشطة" value={counts.active} color="#00E676" icon={<Radar size={17} />} />
        <SummaryTile label="مكتملة" value={counts.completed} color="#B388FF" icon={<ShieldAlert size={17} />} />
      </Box>

      <Card>
        <CardContent sx={{ p: 2, pb: 1.2 }}>
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            spacing={1.25}
            alignItems={{ xs: 'stretch', md: 'center' }}
            justifyContent="space-between"
          >
            <TextField
              size="small"
              placeholder="ابحث باسم الحملة…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ width: { xs: '100%', md: 300 } }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Search size={16} color="#8B9BB4" />
                  </InputAdornment>
                ),
              }}
            />
            <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', gap: 0.75 }}>
              {FILTERS.map((item) => (
                <Chip
                  key={item.value}
                  label={item.label}
                  clickable
                  onClick={() => setFilter(item.value)}
                  color={filter === item.value ? 'primary' : 'default'}
                  variant={filter === item.value ? 'filled' : 'outlined'}
                  size="small"
                />
              ))}
            </Stack>
          </Stack>
        </CardContent>

        {campaignsQuery.isLoading ? (
          <LoadingState label="جارٍ تحميل الحملات…" />
        ) : campaignsQuery.error ? (
          <Box sx={{ p: 2 }}>
            <Alert severity="error">{errorMessage(campaignsQuery.error)}</Alert>
          </Box>
        ) : filtered.length === 0 ? (
          <EmptyState
            title={campaigns.length === 0 ? 'لا توجد حملات بعد' : 'لا توجد نتائج مطابقة'}
            description={
              campaigns.length === 0
                ? 'أنشئ حملة، اختر قالباً، وحدّد الموظفين المستهدفين.'
                : 'جرّب تغيير كلمة البحث أو الفلتر.'
            }
          />
        ) : (
          <TableContainer>
            <Table size="small" className="mc-table-stagger">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ minWidth: 250 }}>اسم الحملة</TableCell>
                  <TableCell>الحالة</TableCell>
                  <TableCell align="center">المستهدفون</TableCell>
                  <TableCell align="center">أُرسل</TableCell>
                  <TableCell align="center">فُتح</TableCell>
                  <TableCell align="center">نُقر</TableCell>
                  <TableCell align="center">اكتمل</TableCell>
                  <TableCell>التاريخ</TableCell>
                  <TableCell align="center">إجراءات</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filtered.map((campaign) => (
                  <TableRow key={campaign.id} hover className="mc-hover-row">
                    <TableCell>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Box
                          sx={{
                            width: 32,
                            height: 32,
                            borderRadius: 1.75,
                            display: 'grid',
                            placeItems: 'center',
                            color: campaign.status === 'active' ? 'success.main' : 'primary.main',
                            bgcolor:
                              campaign.status === 'active'
                                ? 'rgba(0,230,118,.07)'
                                : 'rgba(0,240,255,.06)',
                            border:
                              campaign.status === 'active'
                                ? '1px solid rgba(0,230,118,.20)'
                                : '1px solid rgba(0,240,255,.14)',
                          }}
                        >
                          <Megaphone size={15} />
                        </Box>
                        <Box sx={{ minWidth: 0 }}>
                          <Link
                            component={RouterLink}
                            to={`/campaigns/${campaign.id}`}
                            underline="none"
                            sx={{
                              fontWeight: 700,
                              color: 'text.primary',
                              display: 'block',
                              lineHeight: 1.5,
                              '&:hover': { color: 'primary.main' },
                            }}
                          >
                            {campaign.name}
                          </Link>
                          <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.64rem' }}>
                            {campaign.total_targets} هدف · {campaign.failed_count} فشل
                          </Typography>
                        </Box>
                      </Stack>
                    </TableCell>
                    <TableCell>
                      <CampaignStatusBadge status={campaign.status} />
                    </TableCell>
                    <TableCell align="center" className="mc-mono">{campaign.total_targets}</TableCell>
                    <TableCell align="center" className="mc-mono">{campaign.sent_count}</TableCell>
                    <TableCell align="center" className="mc-mono" sx={{ color: 'info.main' }}>{campaign.opened_count}</TableCell>
                    <TableCell align="center" className="mc-mono" sx={{ color: 'warning.main' }}>{campaign.clicked_count}</TableCell>
                    <TableCell align="center" className="mc-mono" sx={{ color: 'success.main' }}>{campaign.completed_count}</TableCell>
                    <TableCell sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}>{formatDate(campaign.created_at)}</TableCell>
                    <TableCell align="center">
                      <Stack direction="row" spacing={0.25} justifyContent="center" className="mc-row-actions">
                        <Tooltip title="تفاصيل الحملة">
                          <IconButton size="small" onClick={() => navigate(`/campaigns/${campaign.id}`)}>
                            <Eye size={15} />
                          </IconButton>
                        </Tooltip>
                        {campaign.status !== 'draft' ? (
                          <Tooltip title="لوحة المراقبة الحية">
                            <IconButton
                              size="small"
                              color="success"
                              onClick={() => navigate(`/campaigns/${campaign.id}/live`)}
                            >
                              <Radar size={15} />
                            </IconButton>
                          </Tooltip>
                        ) : null}
                        {campaign.status === 'draft' ? (
                          <>
                            <Tooltip title="إطلاق الآن">
                              <span>
                                <IconButton
                                  size="small"
                                  color="primary"
                                  disabled={launchMutation.isPending}
                                  onClick={() => launchMutation.mutate(campaign)}
                                >
                                  <Play size={15} />
                                </IconButton>
                              </span>
                            </Tooltip>
                            <Tooltip title="حذف المسودة">
                              <IconButton size="small" color="error" onClick={() => setPendingDelete(campaign)}>
                                <Trash2 size={15} />
                              </IconButton>
                            </Tooltip>
                          </>
                        ) : (
                          <Tooltip title="فتح">
                            <IconButton size="small" onClick={() => navigate(`/campaigns/${campaign.id}`)}>
                              <ArrowUpRight size={15} />
                            </IconButton>
                          </Tooltip>
                        )}
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Card>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="حذف المسودة"
        message={`حذف المسودة «${pendingDelete?.name ?? ''}»؟ لا يمكن التراجع.`}
        confirmLabel="حذف"
        destructive
        busy={deleteMutation.isPending}
        onConfirm={() => pendingDelete && deleteMutation.mutate(pendingDelete)}
        onClose={() => setPendingDelete(null)}
      />

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.35, duration: 0.4 }}
        style={{ marginTop: 12, textAlign: 'center' }}
      >
        <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.66rem' }}>
          كل إطلاق يمر بفحص تسليم إلزامي قبل إرسال أي رسالة حقيقية.
        </Typography>
      </motion.div>
    </>
  );
}
