import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export interface TableViewerData {
  headers: string[];
  rows: string[][];
  /** Per-cell link hrefs, matching rows dimensions. undefined = no link. */
  links?: (string | undefined)[][];
  title?: string;
}

interface TableViewerContextType {
  tableData: TableViewerData | null;
  isOpen: boolean;
  openTable: (data: TableViewerData) => void;
  closeTable: () => void;
}

const TableViewerContext = createContext<TableViewerContextType | undefined>(
  undefined,
);

export function TableViewerProvider({ children }: { children: ReactNode }) {
  const [tableData, setTableData] = useState<TableViewerData | null>(null);
  const [isOpen, setIsOpen] = useState(false);

  const openTable = useCallback((data: TableViewerData) => {
    setTableData(data);
    setIsOpen(true);
  }, []);

  const closeTable = useCallback(() => {
    setIsOpen(false);
  }, []);

  const value = useMemo(
    () => ({ tableData, isOpen, openTable, closeTable }),
    [tableData, isOpen, openTable, closeTable],
  );

  return (
    <TableViewerContext.Provider value={value}>
      {children}
    </TableViewerContext.Provider>
  );
}

export function useTableViewer(): TableViewerContextType {
  const ctx = useContext(TableViewerContext);
  if (!ctx) {
    // Graceful fallback outside provider
    return {
      tableData: null,
      isOpen: false,
      // eslint-disable-next-line @typescript-eslint/no-empty-function
      openTable: () => {},
      // eslint-disable-next-line @typescript-eslint/no-empty-function
      closeTable: () => {},
    };
  }
  return ctx;
}
