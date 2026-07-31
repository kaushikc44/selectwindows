import { useNavigation, useRoute, RouteProp } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import * as ImagePicker from "expo-image-picker";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";

import AuthedImage from "../components/AuthedImage";
import {
  attachmentUrl,
  listReferencePhotos,
  ReferencePhoto,
  uploadDimensionPhoto,
  uploadManualDimension,
  uploadReferencePhoto,
} from "../api/quotes";
import { PhotoUploadResult } from "../api/types";
import { useDraft } from "../draft/DraftContext";
import { RootStackParamList } from "../navigation/types";
import { colors, shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "Capture">;
type Rt = RouteProp<RootStackParamList, "Capture">;

type FieldState =
  | { status: "empty" }
  | { status: "uploading" }
  | { status: "resolved"; valueMm: number; multiReading: boolean }
  | { status: "unreadable" }
  | { status: "conflict"; values: number[] };

function FieldCapture({
  label,
  field,
  state,
  onCapture,
  onManualEntry,
}: {
  label: string;
  field: "width" | "height";
  state: FieldState;
  onCapture: () => void;
  onManualEntry: (valueMm: number) => void;
}) {
  const [enteringManually, setEnteringManually] = useState(false);
  const [manualValue, setManualValue] = useState("");

  const saveManualEntry = () => {
    const valueMm = parseInt(manualValue, 10);
    if (!Number.isFinite(valueMm) || valueMm <= 0) return;
    onManualEntry(valueMm);
    setEnteringManually(false);
    setManualValue("");
  };

  return (
    <View style={shared.card}>
      <Text style={shared.h2}>{label}</Text>

      {state.status === "empty" && <Text style={shared.muted}>No photo yet.</Text>}
      {state.status === "uploading" && (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <ActivityIndicator />
          <Text style={shared.muted}>Reading measurement…</Text>
        </View>
      )}
      {state.status === "resolved" && (
        <View style={{ gap: 4 }}>
          <Text style={{ fontSize: 20, fontWeight: "700", color: colors.accent }}>{state.valueMm} mm</Text>
          {state.multiReading && (
            <Text style={shared.muted}>
              Resolved from more than one reading (took the smaller, tighter-fit measurement) — worth a quick
              double check.
            </Text>
          )}
        </View>
      )}
      {state.status === "unreadable" && (
        <Text style={shared.errorText}>Couldn&apos;t read a measurement in that photo — try again, closer and
          in focus.</Text>
      )}
      {state.status === "conflict" && (
        <Text style={shared.errorText}>
          Got two different readings for this edge: {state.values.join("mm vs ")}mm — too far apart to trust.
          Retake a clearer photo.
        </Text>
      )}

      <TouchableOpacity style={shared.buttonSecondary} onPress={onCapture} disabled={state.status === "uploading"}>
        <Text style={shared.buttonSecondaryText}>
          {state.status === "resolved"
            ? "Choose a Different Screenshot"
            : `Choose ${field === "width" ? "Width" : "Height"} Screenshot`}
        </Text>
      </TouchableOpacity>

      {enteringManually ? (
        <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
          <TextInput
            style={[shared.input, { flex: 1 }]}
            value={manualValue}
            onChangeText={setManualValue}
            keyboardType="number-pad"
            placeholder="mm"
            autoFocus
          />
          <TouchableOpacity style={shared.button} onPress={saveManualEntry}>
            <Text style={shared.buttonText}>Save</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <TouchableOpacity onPress={() => setEnteringManually(true)} disabled={state.status === "uploading"}>
          <Text style={[shared.muted, { textAlign: "center", textDecorationLine: "underline" }]}>
            Or type it in
          </Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

export default function CaptureScreen() {
  const navigation = useNavigation<Nav>();
  const { params } = useRoute<Rt>();
  const { setItemDimension } = useDraft();

  const [width, setWidth] = useState<FieldState>({ status: "empty" });
  const [height, setHeight] = useState<FieldState>({ status: "empty" });
  const [permissionError, setPermissionError] = useState<string | null>(null);
  const [referencePhotos, setReferencePhotos] = useState<ReferencePhoto[]>([]);
  const [uploadingReference, setUploadingReference] = useState(false);

  useEffect(() => {
    listReferencePhotos(params.quoteId, params.itemId)
      .then(setReferencePhotos)
      .catch(() => {});
  }, [params.quoteId, params.itemId]);

  const requestCamera = async (): Promise<boolean> => {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      setPermissionError("Camera permission is required to capture photos.");
      return false;
    }
    setPermissionError(null);
    return true;
  };

  const requestLibrary = async (): Promise<boolean> => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setPermissionError("Photos permission is required to choose the Measure app screenshot.");
      return false;
    }
    setPermissionError(null);
    return true;
  };

  const applyUploadResult = (field: "width" | "height", upload: PhotoUploadResult) => {
    const setState = field === "width" ? setWidth : setHeight;
    if (upload.resolved && upload.value_mm !== null) {
      setState({ status: "resolved", valueMm: upload.value_mm, multiReading: upload.multi_reading });
      setItemDimension(params.itemId, field, upload.value_mm);
    } else if (upload.reason === "conflict" && upload.conflict_values_mm) {
      setState({ status: "conflict", values: upload.conflict_values_mm });
    } else {
      setState({ status: "unreadable" });
    }
  };

  // Measurements come from Apple's Measure app, not our camera — iOS gives no
  // way to launch Measure and get a result back, so the worker takes the AR
  // reading in Measure, screenshots it, then picks that screenshot here.
  const capture = async (field: "width" | "height") => {
    const setState = field === "width" ? setWidth : setHeight;

    if (!(await requestLibrary())) return;

    const result = await ImagePicker.launchImageLibraryAsync({ quality: 0.8 });
    if (result.canceled || !result.assets?.[0]) return;

    setState({ status: "uploading" });
    try {
      const upload = await uploadDimensionPhoto(params.quoteId, params.itemId, field, result.assets[0].uri);
      applyUploadResult(field, upload);
    } catch (err) {
      setState({ status: "unreadable" });
    }
  };

  const manualEntry = async (field: "width" | "height", valueMm: number) => {
    const setState = field === "width" ? setWidth : setHeight;
    setState({ status: "uploading" });
    try {
      const upload = await uploadManualDimension(params.quoteId, params.itemId, field, valueMm);
      applyUploadResult(field, upload);
    } catch (err) {
      setState({ status: "unreadable" });
    }
  };

  const captureReference = async () => {
    if (!(await requestCamera())) return;

    const result = await ImagePicker.launchCameraAsync({ quality: 0.7 });
    if (result.canceled || !result.assets?.[0]) return;

    setUploadingReference(true);
    try {
      const photo = await uploadReferencePhoto(params.quoteId, params.itemId, result.assets[0].uri);
      setReferencePhotos((photos) => [...photos, photo]);
    } catch (err) {
      // Best-effort — a failed reference photo isn't blocking, just try again.
    } finally {
      setUploadingReference(false);
    }
  };

  const bothDone = width.status === "resolved" && height.status === "resolved";

  return (
    <ScrollView style={shared.screen} contentContainerStyle={shared.scrollContent}>
      <Text style={shared.h1}>{params.itemLabel}</Text>
      <Text style={shared.muted}>
        For each measurement: open the Measure app, take the AR reading against that edge, then screenshot it (side
        button + volume up). Come back here and choose that screenshot below — one photo per edge, with just that
        one reading visible.
      </Text>

      {permissionError && <Text style={shared.errorText}>{permissionError}</Text>}

      <FieldCapture
        label="Width"
        field="width"
        state={width}
        onCapture={() => capture("width")}
        onManualEntry={(valueMm) => manualEntry("width", valueMm)}
      />
      <FieldCapture
        label="Height"
        field="height"
        state={height}
        onCapture={() => capture("height")}
        onManualEntry={(valueMm) => manualEntry("height", valueMm)}
      />

      <View style={shared.card}>
        <Text style={shared.h2}>Reference Photos</Text>
        <Text style={shared.muted}>
          {referencePhotos.length === 0
            ? "No reference photos yet — optional, for site context (not a measurement)."
            : `${referencePhotos.length} photo${referencePhotos.length === 1 ? "" : "s"} attached.`}
        </Text>
        {referencePhotos.length > 0 && (
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {referencePhotos.map((photo) => (
              <AuthedImage
                key={photo.attachment_id}
                uri={attachmentUrl(photo.attachment_id)}
                style={{ width: 72, height: 72, borderRadius: 8, backgroundColor: colors.line }}
              />
            ))}
          </View>
        )}
        <TouchableOpacity style={shared.buttonSecondary} onPress={captureReference} disabled={uploadingReference}>
          {uploadingReference ? (
            <ActivityIndicator />
          ) : (
            <Text style={shared.buttonSecondaryText}>+ Add Photo</Text>
          )}
        </TouchableOpacity>
      </View>

      <TouchableOpacity
        style={[shared.button, !bothDone && { opacity: 0.4 }]}
        disabled={!bothDone}
        onPress={() => navigation.navigate("Items", { quoteId: params.quoteId })}
      >
        <Text style={shared.buttonText}>Done</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}
