import { useNavigation, useRoute, RouteProp } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useState } from "react";
import { ActivityIndicator, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";

import { ApiError } from "../api/client";
import { resubmitQuote, submitQuote } from "../api/quotes";
import { PRODUCT_TYPE_LABELS } from "../api/types";
import { useDraft } from "../draft/DraftContext";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "ReviewSubmit">;
type Rt = RouteProp<RootStackParamList, "ReviewSubmit">;

export default function ReviewSubmitScreen() {
  const navigation = useNavigation<Nav>();
  const { params } = useRoute<Rt>();
  const { clientName, items, status, reset } = useDraft();
  const isResubmit = status === "changes_requested";

  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const onSubmit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      if (isResubmit) {
        await resubmitQuote(params.quoteId, note);
      } else {
        await submitQuote(params.quoteId);
      }
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Couldn't submit — try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <View style={[shared.screen, { justifyContent: "center", padding: 24, gap: 16 }]}>
        <Text style={[shared.h1, { textAlign: "center" }]}>{isResubmit ? "Resent ✓" : "Job Submitted ✓"}</Text>
        <Text style={[shared.muted, { textAlign: "center" }]}>
          Pricing and approval are being generated now — the office will review it shortly.
        </Text>
        <TouchableOpacity
          style={shared.button}
          onPress={() => {
            reset();
            navigation.reset({ index: 0, routes: [{ name: "JobList" }] });
          }}
        >
          <Text style={shared.buttonText}>Start Next Job</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <ScrollView style={shared.screen} contentContainerStyle={shared.scrollContent}>
      <Text style={shared.h1}>{isResubmit ? "Review & Resend" : "Review & Submit"}</Text>
      <Text style={shared.muted}>Client: {clientName}</Text>

      {items.map((item) => (
        <View key={item.item_id} style={shared.card}>
          <Text style={{ fontWeight: "700", color: colors.ink }}>
            Item {item.item_no}: {PRODUCT_TYPE_LABELS[item.product_type]}
          </Text>
          <Text style={shared.muted}>
            {item.material} · {item.room ?? "room not set"} · {item.width_mm} × {item.height_mm} mm
          </Text>
        </View>
      ))}

      {isResubmit && (
        <View style={shared.card}>
          <Text style={shared.h2}>Note back to the office (optional)</Text>
          <TextInput
            style={[shared.input, { minHeight: 60, textAlignVertical: "top" }]}
            value={note}
            onChangeText={setNote}
            multiline
            placeholder="e.g. Added the safety glass note as requested"
          />
        </View>
      )}

      {error && <Text style={shared.errorText}>{error}</Text>}

      <TouchableOpacity style={shared.button} onPress={onSubmit} disabled={submitting}>
        {submitting ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={shared.buttonText}>{isResubmit ? "Resend to Office" : "Submit Job"}</Text>
        )}
      </TouchableOpacity>
    </ScrollView>
  );
}
