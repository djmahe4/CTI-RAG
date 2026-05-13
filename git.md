# Git Workflow Guide

## 🌿 Creating and Pushing a New Branch

### 1. Create and Switch to a New Branch
```bash
git checkout -b <new-branch-name>
```

### 2. Implement Changes
*Edit, add, or refactor your code as needed.*

### 3. Stage and Commit Changes
```bash
git add .
git commit -m "Detailed description of your changes"
```

### 4. Push Branch to Remote Repository
```bash
# Sets upstream tracking automatically
git push -u origin <new-branch-name>
```

---

## 🔀 Merging Branches

### 1. Fetch Remote Updates
```bash
git fetch origin <branch-name>
```

### 2. Switch to the Target Branch
```bash
git checkout <branch-name>
```

### 3. Verify Status and History
```bash
git status
git log --oneline --graph --decorate
```

### 4. Prepare Main Branch for Merge
```bash
git checkout master
```

### 5. Review Differences
```bash
# View unique commits on the feature branch
git log master..<branch-name> --oneline

# View code-level differences
git diff master..<branch-name>
```

### 6. Execute Merge
```bash
git merge <branch-name>
```

### 7. Clean Up (Optional)
```bash
# Delete the local feature branch after a successful merge
git branch -d <branch-name>
```