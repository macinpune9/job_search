"use client";
import { useEffect } from "react";
import { token } from "@/lib/api";

export default function Home() {
  useEffect(() => {
    window.location.replace(token.get() ? "/dashboard" : "/login");
  }, []);
  return null;
}
