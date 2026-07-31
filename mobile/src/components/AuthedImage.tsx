import React, { useEffect, useState } from "react";
import { Image, ImageStyle, StyleProp } from "react-native";

import { getToken } from "../api/client";

// Every worker-app endpoint (including GET /worker/attachments/{id}) requires
// a bearer token, so a plain <Image source={{uri}}> can't load it — the
// request needs an Authorization header attached, which RN's Image supports
// via source.headers once we've resolved the token from SecureStore.
export default function AuthedImage({ uri, style }: { uri: string; style?: StyleProp<ImageStyle> }) {
  const [headers, setHeaders] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    getToken().then((token) => {
      if (!cancelled) setHeaders(token ? { Authorization: `Bearer ${token}` } : {});
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!headers) return null;

  return <Image source={{ uri, headers }} style={style} />;
}
