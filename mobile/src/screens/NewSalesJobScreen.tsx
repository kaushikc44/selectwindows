import { useNavigation } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";

import { ApiError } from "../api/client";
import { createSalesJob, listTradies, Tradie } from "../api/sales";
import AddressAutocomplete from "../components/AddressAutocomplete";
import ChipPicker from "../components/ChipPicker";
import { RootStackParamList } from "../navigation/types";
import { shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "NewSalesJob">;

const DATE_FORMAT = /^\d{4}-\d{2}-\d{2}$/;

export default function NewSalesJobScreen() {
  const navigation = useNavigation<Nav>();

  const [clientName, setClientName] = useState("");
  const [contactName, setContactName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [clientAddress, setClientAddress] = useState("");
  const [jobNo, setJobNo] = useState("");

  const [tradies, setTradies] = useState<Tradie[]>([]);
  const [tradieId, setTradieId] = useState<string | null>(null);
  const [scheduledDate, setScheduledDate] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTradies()
      .then(setTradies)
      .catch(() => setError("Couldn't load the tradie list — try again."));
  }, []);

  const onSave = async () => {
    if (!clientName.trim()) {
      setError("Client name is required.");
      return;
    }
    if (!tradieId) {
      setError("Choose which tradie to assign this job to.");
      return;
    }
    if (!DATE_FORMAT.test(scheduledDate.trim())) {
      setError("Scheduled date must be in YYYY-MM-DD format.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await createSalesJob({
        client_name: clientName.trim(),
        contact_name: contactName.trim() || null,
        phone: phone.trim() || null,
        email: email.trim() || null,
        client_address: clientAddress.trim() || null,
        job_no: jobNo.trim() || null,
        assigned_tradie_id: tradieId,
        scheduled_date: scheduledDate.trim(),
      });
      navigation.goBack();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Couldn't create the job — try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ScrollView style={shared.screen} contentContainerStyle={shared.scrollContent}>
      <Text style={shared.h1}>New Job</Text>

      <View style={shared.card}>
        <Text style={shared.h2}>Customer</Text>
        <View>
          <Text style={shared.label}>Client name *</Text>
          <TextInput style={shared.input} value={clientName} onChangeText={setClientName} />
        </View>
        <View>
          <Text style={shared.label}>Contact name (if different)</Text>
          <TextInput style={shared.input} value={contactName} onChangeText={setContactName} />
        </View>
        <View>
          <Text style={shared.label}>Phone</Text>
          <TextInput style={shared.input} value={phone} onChangeText={setPhone} keyboardType="phone-pad" />
        </View>
        <View>
          <Text style={shared.label}>Email</Text>
          <TextInput
            style={shared.input}
            value={email}
            onChangeText={setEmail}
            keyboardType="email-address"
            autoCapitalize="none"
          />
        </View>
        <View>
          <AddressAutocomplete value={clientAddress} onChange={setClientAddress} />
        </View>
        <View>
          <Text style={shared.label}>Job number (office reference, optional)</Text>
          <TextInput style={shared.input} value={jobNo} onChangeText={setJobNo} />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Assign &amp; Schedule</Text>
        <View>
          <Text style={shared.label}>Tradie</Text>
          <ChipPicker
            options={tradies.map((t) => ({ value: t.id, label: t.name }))}
            value={tradieId}
            onChange={setTradieId}
          />
          {tradies.length === 0 && <Text style={shared.muted}>No tradie accounts found.</Text>}
        </View>
        <View>
          <Text style={shared.label}>Scheduled date (YYYY-MM-DD)</Text>
          <TextInput
            style={shared.input}
            value={scheduledDate}
            onChangeText={setScheduledDate}
            placeholder="2026-08-05"
            autoCapitalize="none"
          />
        </View>
      </View>

      {error && <Text style={shared.errorText}>{error}</Text>}

      <TouchableOpacity style={shared.button} onPress={onSave} disabled={submitting}>
        {submitting ? <ActivityIndicator color="#fff" /> : <Text style={shared.buttonText}>Create Job</Text>}
      </TouchableOpacity>
    </ScrollView>
  );
}
