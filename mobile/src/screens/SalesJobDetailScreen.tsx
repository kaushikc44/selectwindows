import { useRoute, RouteProp } from "@react-navigation/native";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";

import { ApiError } from "../api/client";
import { getSalesJob, rescheduleJob, SalesJobDetail } from "../api/sales";
import { RESCHEDULE_REASON_LABELS, RESCHEDULE_REASONS, RescheduleReason } from "../api/types";
import ChipPicker from "../components/ChipPicker";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Rt = RouteProp<RootStackParamList, "SalesJobDetail">;

const STATUS_LABELS: Record<string, string> = {
  scheduled: "Scheduled",
  draft: "In progress on site",
  extracted: "Processing",
  pending_approval: "Awaiting office approval",
  approved: "Approved",
  rejected: "Rejected",
  needs_manual: "Needs manual review",
  changes_requested: "Changes requested",
  missed: "Missed visit",
};

const RESCHEDULABLE_STATUSES = new Set(["scheduled", "missed"]);
const DATE_FORMAT = /^\d{4}-\d{2}-\d{2}$/;

export default function SalesJobDetailScreen() {
  const { params } = useRoute<Rt>();

  const [detail, setDetail] = useState<SalesJobDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [rescheduling, setRescheduling] = useState(false);
  const [newDate, setNewDate] = useState("");
  const [reason, setReason] = useState<RescheduleReason | null>(null);
  const [otherDetail, setOtherDetail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    getSalesJob(params.quoteId)
      .then(setDetail)
      .catch(() => setLoadError("Couldn't load this job — try again."));
  };

  useEffect(load, [params.quoteId]);

  const onReschedule = async () => {
    if (!DATE_FORMAT.test(newDate.trim())) {
      setError("New date must be in YYYY-MM-DD format.");
      return;
    }
    if (!reason) {
      setError("Choose a reason for the reschedule.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await rescheduleJob(params.quoteId, newDate.trim(), reason, otherDetail.trim() || undefined);
      setRescheduling(false);
      setNewDate("");
      setReason(null);
      setOtherDetail("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Couldn't reschedule — try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loadError && !detail) {
    return (
      <View style={[shared.screen, { justifyContent: "center", padding: 24 }]}>
        <Text style={shared.errorText}>{loadError}</Text>
      </View>
    );
  }

  if (!detail) {
    return (
      <View style={[shared.screen, { justifyContent: "center" }]}>
        <ActivityIndicator />
      </View>
    );
  }

  const canReschedule = RESCHEDULABLE_STATUSES.has(detail.status);

  return (
    <ScrollView style={shared.screen} contentContainerStyle={shared.scrollContent}>
      <Text style={shared.h1}>{detail.client_name ?? "Unnamed job"}</Text>
      <Text style={shared.muted}>{(STATUS_LABELS[detail.status] ?? detail.status).toUpperCase()}</Text>

      <View style={shared.card}>
        <Text style={shared.h2}>Customer</Text>
        {detail.phone && <Text style={shared.muted}>Phone: {detail.phone}</Text>}
        {detail.email && <Text style={shared.muted}>Email: {detail.email}</Text>}
        {detail.client_address && <Text style={shared.muted}>Site: {detail.client_address}</Text>}
        {detail.job_no && <Text style={shared.muted}>Job #: {detail.job_no}</Text>}
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Schedule</Text>
        <Text style={shared.muted}>Tradie: {detail.assigned_tradie_name ?? "Unassigned"}</Text>
        <Text style={shared.muted}>Visit date: {detail.scheduled_date ?? "not set"}</Text>
      </View>

      {detail.comments.length > 0 && (
        <View style={shared.card}>
          <Text style={shared.h2}>History</Text>
          {detail.comments.map((c) => (
            <View key={c.id} style={{ gap: 2 }}>
              <Text style={{ fontWeight: "700", color: colors.ink, fontSize: 13 }}>
                {c.author === "sales" ? "You" : c.author === "tradie" ? "Tradie" : "Office"}
                {c.action ? ` · ${c.action.replace("_", " ")}` : ""}
              </Text>
              <Text style={shared.muted}>{c.body}</Text>
            </View>
          ))}
        </View>
      )}

      {canReschedule && (
        <View style={shared.card}>
          <Text style={shared.h2}>Reschedule</Text>
          {!rescheduling ? (
            <TouchableOpacity style={shared.buttonSecondary} onPress={() => setRescheduling(true)}>
              <Text style={shared.buttonSecondaryText}>Reschedule This Job</Text>
            </TouchableOpacity>
          ) : (
            <>
              <View>
                <Text style={shared.label}>New date (YYYY-MM-DD)</Text>
                <TextInput
                  style={shared.input}
                  value={newDate}
                  onChangeText={setNewDate}
                  placeholder="2026-08-08"
                  autoCapitalize="none"
                />
              </View>
              <View>
                <Text style={shared.label}>Reason</Text>
                <ChipPicker
                  options={RESCHEDULE_REASONS.map((r) => ({ value: r, label: RESCHEDULE_REASON_LABELS[r] }))}
                  value={reason}
                  onChange={setReason}
                />
              </View>
              {reason === "other" && (
                <View>
                  <Text style={shared.label}>Details</Text>
                  <TextInput style={shared.input} value={otherDetail} onChangeText={setOtherDetail} />
                </View>
              )}
              {error && <Text style={shared.errorText}>{error}</Text>}
              <TouchableOpacity style={shared.button} onPress={onReschedule} disabled={submitting}>
                {submitting ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={shared.buttonText}>Confirm Reschedule</Text>
                )}
              </TouchableOpacity>
            </>
          )}
        </View>
      )}
    </ScrollView>
  );
}
