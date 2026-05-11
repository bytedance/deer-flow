"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  componentName: string;
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class BlockErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error(`[GenUI] Error in ${this.props.componentName}:`, error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950">
          <p className="text-sm font-medium text-red-800 dark:text-red-200">
            Failed to render {this.props.componentName}
          </p>
          <p className="mt-1 text-xs text-red-600 dark:text-red-400">
            {this.state.error?.message}
          </p>
        </div>
      );
    }

    return this.props.children;
  }
}
