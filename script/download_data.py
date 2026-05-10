from datasets import load_dataset

def main():
    print("1. 데이터셋 다운로드 및 로드 중 (메모리 매핑 방식)...")
    # split="train"으로 지정하여 전체 데이터를 불러옵니다.
    dataset = load_dataset("nvidia/Nemotron-Personas-Korea", split="train")
    
    print(f"원본 데이터 개수: {len(dataset)}개")

    print("2. 만 19세~59세 타겟 필터링 중(19세는 이후 20대 버킷에 포함)...")
    def filter_target_age(example):
        try:
            age = int(example['age'])
            return 19 <= age <= 59
        except (ValueError, KeyError):
            return False

    # filter() 함수는 백그라운드에서 배치로 처리되어 램을 거의 쓰지 않습니다.
    filtered_dataset = dataset.filter(filter_target_age)
    
    print(f"필터링된 데이터 개수: {len(filtered_dataset)}개")

    output_file = "target_personas_20_59.jsonl"
    print(f"3. {output_file} 파일로 저장 중...")
    filtered_dataset.to_json(output_file, force_ascii=False)
    
    print("작업 완료!")

if __name__ == "__main__":
    main()