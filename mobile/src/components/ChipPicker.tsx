import React from "react";
import { Text, TouchableOpacity, View } from "react-native";

import { shared } from "../theme";

interface Option<T extends string> {
  value: T;
  label: string;
}

interface Props<T extends string> {
  options: readonly Option<T>[] | readonly T[];
  value: T | null;
  onChange: (value: T) => void;
}

export default function ChipPicker<T extends string>({ options, value, onChange }: Props<T>) {
  const normalized: Option<T>[] = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));

  return (
    <View style={shared.row}>
      {normalized.map((opt) => {
        const selected = opt.value === value;
        return (
          <TouchableOpacity
            key={opt.value}
            style={[shared.chip, selected && shared.chipSelected]}
            onPress={() => onChange(opt.value)}
          >
            <Text style={[shared.chipText, selected && shared.chipTextSelected]}>{opt.label}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}
