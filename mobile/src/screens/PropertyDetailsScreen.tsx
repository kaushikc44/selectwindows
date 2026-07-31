import { useNavigation, useRoute, RouteProp } from "@react-navigation/native";
import { NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";

import { ApiError } from "../api/client";
import { getMyQuote, reportMissedVisit, setPropertyDetails } from "../api/quotes";
import {
  ExtractionInstallation,
  RESCHEDULE_REASON_LABELS,
  RESCHEDULE_REASONS,
  RescheduleReason,
  RevealLining,
  WATER_RATINGS,
  WIND_RATINGS,
  YES_NO_UNMARKED,
} from "../api/types";
import ChipPicker from "../components/ChipPicker";
import { useDraft } from "../draft/DraftContext";
import { RootStackParamList } from "../navigation/types";
import { shared } from "../theme";

type Nav = NativeStackNavigationProp<RootStackParamList, "PropertyDetails">;
type Rt = RouteProp<RootStackParamList, "PropertyDetails">;

const GLASS_OPTIONS = ["single", "double_glazed", "acoustic", "toughened", "BAL40_pyro"] as const;
const BUILDING_TYPES = ["Residence", "Unit", "Strata", "Other"] as const;
const CONSTRUCTIONS = ["Timber Frame", "B. Veneer", "Cavity Brick", "Other"] as const;
const FLOOR_LEVELS = ["Ground", "1st", "2nd", "3rd"] as const;
const REMOVE_EXISTING = ["Timber", "Aluminium", "Steel", "Prep Openings"] as const;
const SPECIES = ["maple", "pine", "unmarked"] as const;
const DEFINS = ["80", "100", "116", "138", "165", "other", "unmarked"] as const;

function RevealLiningPicker({
  title,
  value,
  onChange,
}: {
  title: string;
  value: RevealLining;
  onChange: (next: RevealLining) => void;
}) {
  return (
    <View style={{ gap: 8 }}>
      <TouchableOpacity
        style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
        onPress={() => onChange({ ...value, selected: !value.selected })}
      >
        <View
          style={{
            width: 20,
            height: 20,
            borderRadius: 4,
            borderWidth: 1.5,
            borderColor: "#2f6f7e",
            backgroundColor: value.selected ? "#2f6f7e" : "transparent",
          }}
        />
        <Text style={shared.muted}>{title}</Text>
      </TouchableOpacity>
      {value.selected && (
        <>
          <ChipPicker options={SPECIES} value={value.species} onChange={(species) => onChange({ ...value, species })} />
          <ChipPicker options={DEFINS} value={value.defin} onChange={(defin) => onChange({ ...value, defin })} />
        </>
      )}
    </View>
  );
}

export default function PropertyDetailsScreen() {
  const navigation = useNavigation<Nav>();
  const { params } = useRoute<Rt>();
  const { startDraft } = useDraft();

  const [clientName, setClientName] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    getMyQuote(params.quoteId)
      .then((quote) => setClientName(quote.client_name))
      .catch(() => setLoadError("Couldn't load this job — try again."));
  }, [params.quoteId]);

  const [colour, setColour] = useState("");
  const [glass, setGlass] = useState<(typeof GLASS_OPTIONS)[number] | null>(null);
  const [windRating, setWindRating] = useState<(typeof WIND_RATINGS)[number]>("unmarked");
  const [waterRating, setWaterRating] = useState<(typeof WATER_RATINGS)[number]>("unmarked");
  const [ventLocks, setVentLocks] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [acousticSeals, setAcousticSeals] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [sumpSills, setSumpSills] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [reveal28, setReveal28] = useState<RevealLining>({ selected: false, species: "unmarked", defin: "unmarked" });
  const [reveal45, setReveal45] = useState<RevealLining>({ selected: false, species: "unmarked", defin: "unmarked" });

  const [buildingType, setBuildingType] = useState<string | null>(null);
  const [construction, setConstruction] = useState<string | null>(null);
  const [floorLevel, setFloorLevel] = useState<string | null>(null);
  const [removeExisting, setRemoveExisting] = useState<string | null>(null);
  const [brickRemovalM2, setBrickRemovalM2] = useState("");
  const [scaffold, setScaffold] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [hoist, setHoist] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [brickSaw, setBrickSaw] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [asbestos, setAsbestos] = useState<(typeof YES_NO_UNMARKED)[number]>("unmarked");
  const [notes, setNotes] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [reportingMissed, setReportingMissed] = useState(false);
  const [missedReason, setMissedReason] = useState<RescheduleReason | null>(null);
  const [missedOtherDetail, setMissedOtherDetail] = useState("");
  const [missedSubmitting, setMissedSubmitting] = useState(false);
  const [missedError, setMissedError] = useState<string | null>(null);

  const onReportMissed = async () => {
    if (!missedReason) {
      setMissedError("Choose a reason.");
      return;
    }
    setMissedError(null);
    setMissedSubmitting(true);
    try {
      await reportMissedVisit(params.quoteId, missedReason, missedOtherDetail.trim() || undefined);
      navigation.reset({ index: 0, routes: [{ name: "JobList" }] });
    } catch (err) {
      setMissedError(err instanceof ApiError ? String(err.detail) : "Couldn't report this — try again.");
    } finally {
      setMissedSubmitting(false);
    }
  };

  const onSubmit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const header = {
        colour: colour.trim() || null,
        glass: glass || null,
        wind_rating: windRating,
        water_rating: waterRating,
        vent_locks: ventLocks,
        acoustic_seals: acousticSeals,
        sump_sills: sumpSills,
        reveal_28: reveal28,
        reveal_45: reveal45,
      };
      const installation: ExtractionInstallation = {
        building_type: buildingType,
        construction,
        floor_level: floorLevel,
        remove_existing: removeExisting,
        brick_removal_m2: brickRemovalM2.trim() ? Number(brickRemovalM2) : null,
        scaffold,
        hoist,
        brick_saw: brickSaw,
        asbestos,
        notes,
      };
      await setPropertyDetails(params.quoteId, header, installation);
      startDraft(params.quoteId, clientName ?? "Job");
      // Reset past PropertyDetails (so "Continue" can't be double-tapped
      // into re-submitting property details twice) but keep JobList
      // underneath, so Items still has a working back button — it just
      // goes to the job list, not the form.
      navigation.reset({
        index: 1,
        routes: [{ name: "JobList" }, { name: "Items", params: { quoteId: params.quoteId } }],
      });
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Couldn't save property details — try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ScrollView style={shared.screen} contentContainerStyle={shared.scrollContent}>
      <Text style={shared.h1}>Property Details</Text>
      {clientName && <Text style={shared.muted}>{clientName}</Text>}
      {loadError && <Text style={shared.errorText}>{loadError}</Text>}

      <View style={shared.card}>
        {!reportingMissed ? (
          <TouchableOpacity onPress={() => setReportingMissed(true)}>
            <Text style={[shared.muted, { textAlign: "center", textDecorationLine: "underline" }]}>
              Can&apos;t complete this visit?
            </Text>
          </TouchableOpacity>
        ) : (
          <>
            <Text style={shared.h2}>Couldn&apos;t Complete This Visit</Text>
            <ChipPicker
              options={RESCHEDULE_REASONS.map((r) => ({ value: r, label: RESCHEDULE_REASON_LABELS[r] }))}
              value={missedReason}
              onChange={setMissedReason}
            />
            {missedReason === "other" && (
              <TextInput
                style={shared.input}
                value={missedOtherDetail}
                onChangeText={setMissedOtherDetail}
                placeholder="What happened?"
              />
            )}
            {missedError && <Text style={shared.errorText}>{missedError}</Text>}
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TouchableOpacity
                style={[shared.buttonSecondary, { flex: 1 }]}
                onPress={() => setReportingMissed(false)}
              >
                <Text style={shared.buttonSecondaryText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[shared.button, { flex: 1 }]}
                onPress={onReportMissed}
                disabled={missedSubmitting}
              >
                {missedSubmitting ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={shared.buttonText}>Report Missed</Text>
                )}
              </TouchableOpacity>
            </View>
          </>
        )}
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Colour &amp; Glass</Text>
        <View>
          <Text style={shared.label}>Colour</Text>
          <TextInput style={shared.input} value={colour} onChangeText={setColour} placeholder="e.g. Surfmist" />
        </View>
        <View>
          <Text style={shared.label}>Glass</Text>
          <ChipPicker options={GLASS_OPTIONS} value={glass} onChange={setGlass} />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Compliance Ratings</Text>
        <View>
          <Text style={shared.label}>Wind rating (Pa)</Text>
          <ChipPicker options={WIND_RATINGS} value={windRating} onChange={setWindRating} />
        </View>
        <View>
          <Text style={shared.label}>Water rating (Pa)</Text>
          <ChipPicker options={WATER_RATINGS} value={waterRating} onChange={setWaterRating} />
        </View>
        <View>
          <Text style={shared.label}>Vent locks</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={ventLocks} onChange={setVentLocks} />
        </View>
        <View>
          <Text style={shared.label}>Acoustic seals</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={acousticSeals} onChange={setAcousticSeals} />
        </View>
        <View>
          <Text style={shared.label}>Sump sills</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={sumpSills} onChange={setSumpSills} />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Reveal Linings</Text>
        <RevealLiningPicker title="28mm reveal" value={reveal28} onChange={setReveal28} />
        <RevealLiningPicker title="45mm reveal" value={reveal45} onChange={setReveal45} />
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Building &amp; Construction</Text>
        <View>
          <Text style={shared.label}>Building type</Text>
          <ChipPicker options={BUILDING_TYPES} value={buildingType} onChange={setBuildingType} />
        </View>
        <View>
          <Text style={shared.label}>Construction</Text>
          <ChipPicker options={CONSTRUCTIONS} value={construction} onChange={setConstruction} />
        </View>
        <View>
          <Text style={shared.label}>Floor level</Text>
          <ChipPicker options={FLOOR_LEVELS} value={floorLevel} onChange={setFloorLevel} />
        </View>
        <View>
          <Text style={shared.label}>Remove existing</Text>
          <ChipPicker options={REMOVE_EXISTING} value={removeExisting} onChange={setRemoveExisting} />
        </View>
        <View>
          <Text style={shared.label}>Brick removal (m²)</Text>
          <TextInput
            style={shared.input}
            value={brickRemovalM2}
            onChangeText={setBrickRemovalM2}
            keyboardType="decimal-pad"
          />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Equipment Hire</Text>
        <View>
          <Text style={shared.label}>Scaffold</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={scaffold} onChange={setScaffold} />
        </View>
        <View>
          <Text style={shared.label}>Hoist</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={hoist} onChange={setHoist} />
        </View>
        <View>
          <Text style={shared.label}>Brick saw</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={brickSaw} onChange={setBrickSaw} />
        </View>
      </View>

      <View style={shared.card}>
        <Text style={shared.h2}>Site Notes</Text>
        <View>
          <Text style={shared.label}>Asbestos present? (Select will not remove)</Text>
          <ChipPicker options={YES_NO_UNMARKED} value={asbestos} onChange={setAsbestos} />
        </View>
        <View>
          <Text style={shared.label}>Additional notes</Text>
          <TextInput
            style={[shared.input, { minHeight: 80, textAlignVertical: "top" }]}
            value={notes}
            onChangeText={setNotes}
            multiline
            placeholder="e.g. large dog on site, customer wants white trim"
          />
        </View>
      </View>

      {error && <Text style={shared.errorText}>{error}</Text>}

      <TouchableOpacity style={shared.button} onPress={onSubmit} disabled={submitting}>
        {submitting ? <ActivityIndicator color="#fff" /> : <Text style={shared.buttonText}>Continue to Items</Text>}
      </TouchableOpacity>
    </ScrollView>
  );
}
