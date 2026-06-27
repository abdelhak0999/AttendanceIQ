import pandas as pd

# File 1: Standard Clean File
df1 = pd.DataFrame({
    'Matricule': [101, 102, 103],
    'Nom': ['KHIARI Alice', 'SADDEK Bob', 'MOHAMED Charlie'],
    'Département': ['RH', 'IT', 'Finance']
})
df1.to_excel('test_employees_standard.xlsx', index=False)

# File 2: Messy File (Testing ID detection logic)
# Column 0 is a sequence (1, 2, 3), Column 2 is the real Matricule
df2 = pd.DataFrame({
    '#': [1, 2, 3],
    'Nom Complet': ['SOUFI David', 'AMARI Eve', 'BELKACEM Frank'],
    'ID_Employee': [201, 202, 203],
    'Note': ['Test 1', 'Test 2', 'Test 3']
})
df2.to_excel('test_employees_messy.xlsx', index=False)

# File 3: Updates and New entries
# 101 and 102 already exist, 301 is new
df3 = pd.DataFrame({
    'Matricule': [101, 102, 301],
    'Nom': ['KHIARI Alice (Updated)', 'SADDEK Bob (Updated)', 'ZAKI Grace'],
    'Direction': ['Direction Générale', 'Direction Technique', 'Direction Commerciale']
})
df3.to_excel('test_employees_updates.xlsx', index=False)

print("✅ 3 test files generated: test_employees_standard.xlsx, test_employees_messy.xlsx, test_employees_updates.xlsx")
