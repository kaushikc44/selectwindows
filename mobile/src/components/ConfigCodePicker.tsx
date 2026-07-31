import React, { useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { SvgXml } from "react-native-svg";

import { getElevationPreview } from "../api/quotes";
import { buildConfigCode, ConfigOption, DIRECTIONS, DOOR_CONFIGS, PANEL_COUNTS, WINDOW_CONFIGS } from "../api/configCodes";
import { shared } from "../theme";
import ChipPicker from "./ChipPicker";

export interface ConfigCodeResult {
  code: string;
  productType: string;
}

interface Props {
  onChange: (result: ConfigCodeResult | null) => void;
}

// Replaces the paper form's hand-drawn configuration grid: tap a type
// (matching the backend's exact config-code vocabulary,
// app/engine/config_codes.py), then a panel count or hinge side if that
// type needs one — never freehand drawing, never typing a code from memory.
// Once enough is picked, fetches a live preview from
// GET /worker/elevation-preview (app/render/elevation.py, unchanged
// server-side logic) instead of leaving the worker to imagine the shape.
export default function ConfigCodePicker({ onChange }: Props) {
  const [category, setCategory] = useState<"window" | "door">("window");
  const [option, setOption] = useState<ConfigOption | null>(null);
  const [panelCount, setPanelCount] = useState<number | null>(null);
  const [direction, setDirection] = useState<"L" | "R" | null>(null);

  const [previewSvg, setPreviewSvg] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const options = category === "window" ? WINDOW_CONFIGS : DOOR_CONFIGS;

  const result: ConfigCodeResult | null =
    option && (!option.needsPanelCount || panelCount) && (!option.needsDirection || direction)
      ? { code: buildConfigCode(option, panelCount, direction), productType: option.productType }
      : null;

  useEffect(() => {
    onChange(result);
    if (!result) {
      setPreviewSvg(null);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    getElevationPreview(result.code)
      .then((svg) => {
        if (!cancelled) setPreviewSvg(svg);
      })
      .catch(() => {
        if (!cancelled) setPreviewSvg(null);
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.code]);

  const selectCategory = (next: "window" | "door") => {
    setCategory(next);
    setOption(null);
    setPanelCount(null);
    setDirection(null);
  };

  const selectOption = (next: ConfigOption) => {
    setOption(next);
    setPanelCount(null);
    setDirection(null);
  };

  return (
    <View style={{ gap: 12 }}>
      <View>
        <Text style={shared.label}>Window or door?</Text>
        <ChipPicker
          options={[
            { value: "window" as const, label: "Window" },
            { value: "door" as const, label: "Door" },
          ]}
          value={category}
          onChange={selectCategory}
        />
      </View>

      <View>
        <Text style={shared.label}>Configuration</Text>
        <ChipPicker
          options={options.map((o) => ({ value: o.code, label: o.label }))}
          value={option?.code ?? null}
          onChange={(code) => selectOption(options.find((o) => o.code === code)!)}
        />
      </View>

      {option?.needsPanelCount && (
        <View>
          <Text style={shared.label}>How many panels?</Text>
          <ChipPicker
            options={PANEL_COUNTS.map((n) => ({ value: String(n), label: `${n}` }))}
            value={panelCount !== null ? String(panelCount) : null}
            onChange={(v) => setPanelCount(Number(v))}
          />
        </View>
      )}

      {option?.needsDirection && (
        <View>
          <Text style={shared.label}>Hinge side</Text>
          <ChipPicker options={DIRECTIONS} value={direction} onChange={setDirection} />
        </View>
      )}

      {(previewLoading || previewSvg) && (
        <View style={{ alignItems: "center", paddingVertical: 8 }}>
          {previewLoading && <ActivityIndicator />}
          {!previewLoading && previewSvg && <SvgXml xml={previewSvg} width={200} height={160} />}
          {!previewLoading && previewSvg && (
            <Text style={shared.muted}>Preview — actual size shown once measured</Text>
          )}
        </View>
      )}
    </View>
  );
}
